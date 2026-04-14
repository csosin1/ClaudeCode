"""
CapSolver integration for Cloudflare Turnstile (and hCaptcha / reCAPTCHA as fallback).

Usage:
    from capsolver import solve_turnstile
    token = solve_turnstile(page_url='https://www.carvana.com/sell-my-car/getoffer/finalize?...',
                            site_key='0x4AAA...')
    # inject token into the page:
    await page.evaluate(f'''(t) => {{
        const el = document.querySelector('[name="cf-turnstile-response"]');
        if (el) {{ el.value = t; el.dispatchEvent(new Event('input', {{ bubbles: true }})); }}
    }}''', token)

Cost: $0.80 per Turnstile solve (as of Apr 2026). Typical resolve time: 10-30s.
API docs: https://docs.capsolver.com/guide/captcha/turnstile.html
"""
import os, time, json
import urllib.request
from typing import Optional


CAPSOLVER_API_BASE = 'https://api.capsolver.com'
POLL_INTERVAL_S = 3
MAX_POLL_SECONDS = 90

# Per-process spend tracker (complementary to the env cap + invoice from CapSolver)
_spent_usd_this_run = 0.0
_hard_cap_usd = float(os.environ.get('CAPSOLVER_HARD_CAP_USD', '20'))


class CapsolverError(Exception):
    pass


def _http_post_json(url: str, body: dict, timeout: int = 30) -> dict:
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def balance() -> Optional[float]:
    """Current CapSolver balance in USD (or None on error)."""
    key = os.environ.get('CAPSOLVER_API_KEY')
    if not key:
        return None
    try:
        res = _http_post_json(f'{CAPSOLVER_API_BASE}/getBalance', {'clientKey': key})
        if res.get('errorId') == 0:
            return float(res.get('balance', 0))
    except Exception:
        return None
    return None


def solve_turnstile(page_url: str, site_key: str,
                    action: Optional[str] = None,
                    cdata: Optional[str] = None) -> str:
    """
    Submit a Turnstile task and poll until solved. Returns the token string.
    Raises CapsolverError on timeout, bad key, or insufficient balance.

    `site_key` is Cloudflare's sitekey, extracted from the Turnstile widget's
    data-sitekey attribute or the script URL (see extract_turnstile_sitekey below).
    """
    global _spent_usd_this_run
    key = os.environ.get('CAPSOLVER_API_KEY')
    if not key:
        raise CapsolverError('CAPSOLVER_API_KEY not set')
    if _spent_usd_this_run + 0.80 > _hard_cap_usd:
        raise CapsolverError(f'hard spend cap ${_hard_cap_usd} reached this run')

    task = {
        'type': 'AntiTurnstileTaskProxyLess',
        'websiteURL': page_url,
        'websiteKey': site_key,
    }
    if action:
        task['metadata'] = {'action': action}
    if cdata:
        task.setdefault('metadata', {})['cdata'] = cdata

    create = _http_post_json(f'{CAPSOLVER_API_BASE}/createTask', {
        'clientKey': key, 'task': task,
    })
    if create.get('errorId') != 0:
        raise CapsolverError(f'createTask failed: {create.get("errorDescription") or create}')

    task_id = create.get('taskId')
    if not task_id:
        raise CapsolverError(f'no taskId returned: {create}')

    start = time.time()
    while time.time() - start < MAX_POLL_SECONDS:
        time.sleep(POLL_INTERVAL_S)
        result = _http_post_json(f'{CAPSOLVER_API_BASE}/getTaskResult', {
            'clientKey': key, 'taskId': task_id,
        })
        if result.get('errorId') != 0:
            raise CapsolverError(f'getTaskResult failed: {result.get("errorDescription") or result}')
        status = result.get('status')
        if status == 'ready':
            _spent_usd_this_run += 0.80
            token = result.get('solution', {}).get('token')
            if not token:
                raise CapsolverError(f'ready but no token: {result}')
            return token
        if status == 'processing':
            continue
        raise CapsolverError(f'unexpected status "{status}": {result}')

    raise CapsolverError(f'timeout after {MAX_POLL_SECONDS}s polling CapSolver')


async def extract_turnstile_sitekey(page) -> Optional[str]:
    """Pull the data-sitekey from any visible Turnstile widget on the page."""
    try:
        return await page.evaluate('''() => {
            const sel = [
                '[data-sitekey]',
                'iframe[src*="challenges.cloudflare.com"]',
            ];
            for (const s of sel) {
                const el = document.querySelector(s);
                if (el) {
                    const key = el.getAttribute('data-sitekey');
                    if (key) return key;
                    // iframe src often has sitekey as query param
                    const src = el.getAttribute('src') || '';
                    const m = src.match(/sitekey=([^&]+)/i);
                    if (m) return m[1];
                }
            }
            return null;
        }''')
    except Exception:
        return None


async def inject_turnstile_token(page, token: str) -> None:
    """Inject a solved Turnstile token into the page and dispatch input event."""
    await page.evaluate('''(t) => {
        document.querySelectorAll('[name="cf-turnstile-response"], input[name*="turnstile"]').forEach(el => {
            el.value = t;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        });
        // Some pages expect window.turnstile.execute's callback to fire
        if (window.turnstile && typeof window.turnstile._loadOk === 'undefined') {
            try { window.turnstile.reset(); } catch {}
        }
    }''', token)


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == 'test':
        print('balance:', balance())
        if len(sys.argv) >= 4:
            url, key = sys.argv[2], sys.argv[3]
            print('solving...')
            print('token:', solve_turnstile(url, key)[:40] + '...')
    else:
        print(f'balance: {balance()}')
