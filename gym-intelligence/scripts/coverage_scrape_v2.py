#!/usr/bin/env python3
"""Coverage scraper v2 — httpx primary + Playwright fallback.

Per chain: try httpx (fast). If 4xx/5xx OR 200-but-no-pattern, retry via
Playwright (slow but renders JS + better bot evasion). Extract count via
regex/JSON-LD on the final HTML.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
from urllib.parse import urlparse

import httpx

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

LOCATOR_PATHS = [
    "/clubs", "/studios", "/nos-clubs", "/nos-salles", "/gyms",
    "/salle-de-sport", "/salles-de-sport", "/standorte",
    "/fitnessstudios", "/fitnesscenter", "/fitnessstudio-finden",
    "/club-finder", "/clubfinder", "/locations",
    "/nuestros-centros", "/centros",
    "/en/clubs", "/de/studios", "/fr/clubs", "/nl/clubs",
]

COUNT_PATTERNS = [
    r"(?:plus de|more than|over|nos|our|avec|we have|erlebe|entdecke|mit)\s+(\d{2,4})\s+(?:clubs?|salles?|studios?|gyms?|standorten?|centros?|centres?|sedi|palestre|filialen)",
    r"\b(\d{2,4})\s+(?:clubs?|salles?|studios?|gyms?|standorten?)\s+(?:in|en|across|im|dans|à travers|weltweit)",
    r"\b(\d{2,4})\s+(?:club|studio|salle|gym|standort)\b",
]


def root_domain(url):
    p = urlparse(url)
    if not p.scheme:
        p = urlparse("http://" + url)
    return f"{p.scheme}://{p.netloc}"


def candidate_urls(raw_url, limit=8):
    out = [raw_url]
    try:
        root = root_domain(raw_url)
    except Exception:
        return out
    for path in LOCATOR_PATHS:
        out.append(root + path)
    out.append(root)
    seen = set()
    unique = []
    for u in out:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique[:limit]


def strip_html(html):
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def extract_count(html, text):
    schema_n = len(re.findall(
        r'"@type"\s*:\s*"(?:GymLocation|HealthClub|ExerciseGym|SportsActivityLocation|LocalBusiness|Place)"',
        html,
    ))
    if schema_n >= 3:
        return schema_n, f"schema_org_{schema_n}"
    for pat in COUNT_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            n = int(m.group(1))
            if 5 <= n <= 5000:
                return n, f"stated:{m.group(0)[:60]}"
    cities = re.findall(r'"city"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
    if len(set(cities)) >= 5:
        return len(set(cities)), f"json_city_unique_{len(set(cities))}"
    names = re.findall(r'"name"\s*:\s*"([^"]{5,80})"', html)
    # A crude fallback: if we see MANY gym-like names, count them as venue entries
    gym_words = ("fitness", "gym", "club", "salle", "studio", "sport", "bowl", "centre", "center")
    gym_names = [n for n in names if any(w in n.lower() for w in gym_words)]
    if len(set(gym_names)) >= 5:
        return len(set(gym_names)), f"jsonld_gym_names_{len(set(gym_names))}"
    return None, "no_pattern"


def fetch_httpx(client, url):
    try:
        r = client.get(url)
        return r.status_code, r.text, str(r.url)
    except Exception as e:
        return f"err:{type(e).__name__}", "", url


def try_httpx(entry, client, max_urls=6):
    """Return (count, method, url, last_status) or (None, reason, None, last_status)."""
    last_status = None
    for u in candidate_urls(entry["url"], limit=max_urls):
        code, html, final = fetch_httpx(client, u)
        last_status = code
        if isinstance(code, int) and code == 200 and len(html) > 3000:
            text = strip_html(html).lower()
            n, method = extract_count(html, text)
            if n:
                return n, method, final, code
    return None, "httpx_no_count", None, last_status


def try_playwright(entry, browser, max_urls=4):
    """Use a shared browser (one per worker process). Returns same tuple."""
    last_status = None
    for u in candidate_urls(entry["url"], limit=max_urls):
        try:
            page = browser.new_page(
                user_agent=UA,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )
            # Block images/fonts/video for speed (keeps CSS + JS)
            page.route("**/*.{png,jpg,jpeg,webp,gif,svg,woff,woff2,ttf,mp4,webm}", lambda r: r.abort())
            resp = page.goto(u, wait_until="networkidle", timeout=25000)
            status = resp.status if resp else 0
            last_status = status
            if status == 200:
                # Give SPA a moment to hydrate
                try:
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
                html = page.content()
                if len(html) > 3000:
                    text = strip_html(html).lower()
                    n, method = extract_count(html, text)
                    if n:
                        page.close()
                        return n, f"pw:{method}", u, status
            page.close()
        except Exception as e:
            last_status = f"pw_err:{type(e).__name__}"
    return None, "playwright_no_count", None, last_status


def process_one(entry, client, browser, conn):
    out = {
        "chain_id": entry["chain_id"],
        "canonical_name": entry["canonical_name"],
        "location_count": entry["location_count"],
        "original_url": entry["url"],
        "scraped_count": None,
        "method": None,
        "successful_url": None,
        "last_status": None,
        "used_playwright": False,
    }
    n, method, url, status = try_httpx(entry, client)
    if n is None and browser is not None:
        out["used_playwright"] = True
        n, method, url, status = try_playwright(entry, browser)
    out["scraped_count"] = n
    out["method"] = method
    out["successful_url"] = url
    out["last_status"] = status
    oc = conn.execute(
        "SELECT SUM(s.location_count) FROM snapshots s WHERE s.chain_id=? AND s.snapshot_date='2026-03-31'",
        (entry["chain_id"],),
    ).fetchone()[0] or 0
    out["ohsome_2026q1"] = oc
    if n:
        out["delta"] = oc - n
        out["coverage_pct"] = round(100 * oc / n, 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--sleep", type=float, default=1.2)
    ap.add_argument("--no-playwright", action="store_true")
    args = ap.parse_args()

    with open(args.input) as f:
        chains = json.load(f)

    conn = sqlite3.connect("/opt/gym-intelligence-preview/gyms.db")

    browser = None
    pw = None
    if not args.no_playwright:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])

    results = []
    start = time.time()
    bin_name = os.path.basename(args.input).replace(".json", "")
    with httpx.Client(
        follow_redirects=True,
        timeout=18,
        headers={"User-Agent": UA, "Accept-Language": "en,en-US;q=0.9,fr,de,nl,es"},
    ) as client:
        for i, entry in enumerate(chains, 1):
            try:
                r = process_one(entry, client, browser, conn)
            except Exception as e:
                r = {**entry, "error": f"{type(e).__name__}: {e}"}
            results.append(r)
            if i % 5 == 0 or i == len(chains):
                hit = sum(1 for x in results if x.get("scraped_count"))
                pw_hits = sum(1 for x in results if x.get("used_playwright") and x.get("scraped_count"))
                elapsed = time.time() - start
                eta = (len(chains) - i) * (elapsed / i)
                print(
                    f"[{bin_name}] {i}/{len(chains)} hit={hit} (pw_hits={pw_hits}) elapsed={elapsed:.0f}s eta={eta/60:.1f}m",
                    flush=True,
                )
                with open(args.output, "w") as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
            time.sleep(args.sleep)

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    if pw:
        try:
            browser.close()
            pw.stop()
        except Exception:
            pass
    hit = sum(1 for x in results if x.get("scraped_count"))
    print(f"[{bin_name}] DONE: {hit}/{len(chains)}", flush=True)


if __name__ == "__main__":
    main()
