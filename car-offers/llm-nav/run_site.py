#!/usr/bin/env python3
"""
browser-use harness for car-offers sell-flows.

Launches headed Chromium on a chosen Xvfb display, through our Decodo sticky
residential proxy, with our persistent consumer profile + stealth init, then
lets an Anthropic LLM drive the page until it reports a JSON verdict.

Usage:
  python run_site.py --site carvana|carmax|driveway --vin ... --mileage ... \
                     --zip ... --display :100 --profile llmnav-carvana \
                     --session-id llmnav-carvana --max-steps 60
"""

import argparse, asyncio, json, os, pathlib, shutil, sys, time, re
from datetime import datetime

import dotenv
dotenv.load_dotenv('/opt/car-offers-preview/.env')
dotenv.load_dotenv('/opt/gym-intelligence/.env', override=False)  # ANTHROPIC_API_KEY lives here

from browser_use import Agent, BrowserSession, BrowserProfile
from browser_use.browser.profile import ProxySettings
from browser_use.llm import ChatAnthropic

HERE = pathlib.Path('/opt/site-deploy/car-offers/llm-nav')
LOG_ROOT = HERE / 'logs'
STEALTH_INIT = pathlib.Path('/opt/site-deploy/car-offers/lib/stealth-init.js').read_text()

START_URLS = {
    'carvana':  'https://www.carvana.com/sell-my-car',
    'carmax':   'https://www.carmax.com/sell-my-car',
    'driveway': 'https://www.driveway.com/sell-your-car',
}

ZIP_TO_STATE = {'068': 'CT', '067': 'CT', '064': 'CT', '070': 'NJ', '073': 'NJ',
                '100': 'NY', '021': 'MA', '331': 'FL', '787': 'TX', '303': 'GA',
                '606': 'IL', '441': 'OH', '941': 'CA', '981': 'WA', '802': 'CO'}

# Exhaustive per-consumer car-facts sheet. EVERY site gets the SAME answers so
# offers are apples-to-apples. Any question a site asks that isn't here, the
# agent picks the most-conservative/clean option and we log it as 'agent_chose'.
CAR_FACTS = {
    '2HGFE2F5XNH606212': {  # Consumer 2 — Jersey City 2022 Honda Civic Sport
        'exterior_color':       'Silver',
        'interior_color':       'Black',
        'trim':                 'Sport',
        'transmission':         'CVT',
        'drivetrain':           'FWD',
        'accidents':            'No',
        'title':                'Clean, free and clear, owned outright',
        'ownership':            'Own outright, no loan, no lease',
        'modifications':        'None',
        'number_of_keys':       '2 or more',
        'smoked_in':            'No',
        'exterior_damage':      'None',
        'windshield_damage':    'None',
        'interior_damage':      'None',
        'interior_tears':       'None',
        'technology_issues':    'None',
        'engine_issues':        'None',
        'mechanical_issues':    'None',
        'rust_damage':          'None',
        'hail_damage':          'None',
        'flood_damage':         'None',
        'frame_damage':         'None',
        'tires_need_replacing': 'No',
        'drivable':             'Yes',
        'overall_condition':    'Good',
        'paint_bodywork_needed':'No',
        'odometer_issues':      'No',
        'intent':               'Selling only (not trading)',
    },
    'KMHLN4AJ5PU069598': {  # Consumer 4 — Cambridge MA 2023 Hyundai Elantra Limited
        'exterior_color':       'Blue',
        'interior_color':       'Gray',
        'trim':                 'Limited',
        'transmission':         'Automatic',
        'drivetrain':           'FWD',
        'accidents':            'No',
        'title':                'Clean, free and clear, owned outright',
        'ownership':            'Own outright, no loan, no lease',
        'modifications':        'None',
        'number_of_keys':       '2 or more',
        'smoked_in':            'No',
        'exterior_damage':      'None',
        'windshield_damage':    'None',
        'interior_damage':      'None',
        'interior_tears':       'None',
        'technology_issues':    'None',
        'engine_issues':        'None',
        'mechanical_issues':    'None',
        'rust_damage':          'None',
        'hail_damage':          'None',
        'flood_damage':         'None',
        'frame_damage':         'None',
        'tires_need_replacing': 'No',
        'drivable':             'Yes',
        'overall_condition':    'Good',
        'paint_bodywork_needed':'No',
        'odometer_issues':      'No',
        'intent':               'Selling only (not trading)',
    },
    '1HGCV2F9XNA008352': {  # Consumer 1 — Westport 2022 Honda Accord Touring
        'real_mileage':         60624,   # AutoCheck truth — overrides any input mileage
        'exterior_color':       'White',
        'interior_color':       'Black',
        'trim':                 'Touring',
        'transmission':         'Automatic',
        'drivetrain':           'FWD',
        'accidents':            'No',
        'title':                'Clean, free and clear, owned outright',
        'ownership':            'Own outright, no loan, no lease',
        'modifications':        'None',
        'number_of_keys':       '2 or more',
        'smoked_in':            'No',
        'exterior_damage':      'None',
        'windshield_damage':    'None',
        'interior_damage':      'None',
        'interior_tears':       'None',
        'technology_issues':    'None',
        'engine_issues':        'None',
        'mechanical_issues':    'None',
        'rust_damage':          'None',
        'hail_damage':          'None',
        'flood_damage':         'None',
        'frame_damage':         'None',
        'tires_need_replacing': 'No',
        'drivable':             'Yes',
        'overall_condition':    'Good',
        'paint_bodywork_needed':'No',
        'odometer_issues':      'No',
        'intent':               'Selling only (not trading)',
    },
}


# Full persona bio per zip. Permanent — same person, same address, same DL, same phone always.
# Phone numbers are placeholders ("(555) 0xx-xxxx" pattern reserved by NANP for fiction);
# real Twilio numbers slot in once Twilio is provisioned.
PERSONAS = {
    '06880': dict(first='Catherine', middle='B', last='Smith',  email='catherine.b.smith@gmail.com',
                  city='Westport',        state='CT', street='47 Maple Lane',         dob='1984-06-12',
                  dl_state='CT', dl_number='123456789', phone='(203) 555-0142', employment='Employed full-time',
                  years_at_address=8,  years_owned=3),
    '92101': dict(first='Marcus',    middle='J', last='Alvarez', email='marcus.j.alvarez@gmail.com',
                  city='San Diego',       state='CA', street='1234 Island Avenue, Apt 5B', dob='1987-03-21',
                  dl_state='CA', dl_number='B1234567', phone='(619) 555-0177', employment='Employed full-time',
                  years_at_address=4,  years_owned=4),
    '07302': dict(first='Javier',    middle='M', last='Reyes',  email='j.reyes.jc@gmail.com',
                  city='Jersey City',     state='NJ', street='815 Newark Avenue',     dob='1990-11-04',
                  dl_state='NJ', dl_number='R12345678901234', phone='(201) 555-0119', employment='Employed full-time',
                  years_at_address=3,  years_owned=2),
    '10023': dict(first='Morgan',    middle='T', last='Liu',    email='morgan.liu.nyc@gmail.com',
                  city='New York',        state='NY', street='225 W 70th St, Apt 12C', dob='1982-09-30',
                  dl_state='NY', dl_number='123456789', phone='(212) 555-0101', employment='Employed full-time',
                  years_at_address=6,  years_owned=4),
    '02139': dict(first='Alex',      middle='R', last='Mercer', email='amercer.cambridge@gmail.com',
                  city='Cambridge',       state='MA', street='119 Prospect St',       dob='1991-02-15',
                  dl_state='MA', dl_number='S12345678', phone='(617) 555-0188', employment='Employed full-time',
                  years_at_address=2,  years_owned=1),
    '33139': dict(first='Daniela',   middle='C', last='Gomez',  email='dgomez.305@gmail.com',
                  city='Miami Beach',     state='FL', street='1450 Ocean Drive, Apt 7', dob='1986-07-08',
                  dl_state='FL', dl_number='G123456789012', phone='(305) 555-0166', employment='Employed full-time',
                  years_at_address=5,  years_owned=3),
    '78701': dict(first='Kyle',      middle='D', last='Jensen', email='k.jensen.atx@gmail.com',
                  city='Austin',          state='TX', street='1010 W 6th Street',     dob='1983-12-01',
                  dl_state='TX', dl_number='12345678', phone='(512) 555-0133', employment='Employed full-time',
                  years_at_address=7,  years_owned=3),
    '30309': dict(first='Tasha',     middle='L', last='Williams', email='tasha.w.atl@gmail.com',
                  city='Atlanta',         state='GA', street='950 Peachtree St NE, Apt 1404', dob='1988-04-22',
                  dl_state='GA', dl_number='123456789', phone='(404) 555-0155', employment='Employed full-time',
                  years_at_address=4,  years_owned=2),
    '60614': dict(first='Ryan',      middle='M', last='Patterson', email='rpatterson.chi@gmail.com',
                  city='Chicago',         state='IL', street='2143 N Halsted St',     dob='1979-08-17',
                  dl_state='IL', dl_number='P123-4567-8901', phone='(773) 555-0123', employment='Employed full-time',
                  years_at_address=10, years_owned=5),
    '44114': dict(first='Brandon',   middle='K', last='Miller', email='brandon.miller.cle@gmail.com',
                  city='Cleveland',       state='OH', street='1450 Lakeside Ave',     dob='1985-05-14',
                  dl_state='OH', dl_number='AB123456', phone='(216) 555-0102', employment='Employed full-time',
                  years_at_address=6,  years_owned=3),
    '94110': dict(first='Priya',     middle='V', last='Shankar', email='priya.shankar.sf@gmail.com',
                  city='San Francisco',   state='CA', street='3500 24th Street, Apt 4', dob='1989-10-25',
                  dl_state='CA', dl_number='C7654321', phone='(415) 555-0144', employment='Employed full-time',
                  years_at_address=3,  years_owned=2),
    '98121': dict(first='David',     middle='Q', last='Nguyen', email='david.nguyen.sea@gmail.com',
                  city='Seattle',         state='WA', street='2200 Western Avenue, Apt 808', dob='1981-01-09',
                  dl_state='WA', dl_number='NGUYE-D-451-2X', phone='(206) 555-0177', employment='Employed full-time',
                  years_at_address=5,  years_owned=3),
    '80202': dict(first='Hannah',    middle='J', last='Brooks', email='hannah.brooks.den@gmail.com',
                  city='Denver',          state='CO', street='1601 Wynkoop Street, Apt 502', dob='1992-06-03',
                  dl_state='CO', dl_number='12-345-6789', phone='(303) 555-0188', employment='Employed full-time',
                  years_at_address=2,  years_owned=1),
}


def task_prompt(site: str, vin: str, mileage: int, zip_: str, condition: str) -> str:
    state = ZIP_TO_STATE.get(zip_[:3], 'CT')
    persona = PERSONAS.get(zip_, dict(first='Taylor', middle='Q', last='Jones',
                                       email='taylor.jones.shop@gmail.com', city='your city', state=state,
                                       street='100 Main Street', dob='1985-01-15', dl_state=state, dl_number='123456789',
                                       phone='(555) 555-0100', employment='Employed full-time',
                                       years_at_address=5, years_owned=3))
    facts = CAR_FACTS.get(vin, {})

    # Pull in vin_enrich cache if present
    enrich_path = HERE / 'enrichment' / f'{vin}.json'
    enriched = {}
    if enrich_path.exists():
        try:
            enriched = json.loads(enrich_path.read_text()).get('summary', {})
        except Exception:
            pass
    # If facts include a real_mileage, USE IT — ignore the caller's mileage.
    # Sites like Carvana cross-check against AutoCheck and reject wrong values.
    true_mileage = facts.get('real_mileage', mileage)
    facts_block = '\n  '.join(f"{k}: {v}" for k, v in facts.items() if k != 'real_mileage')

    full_name = f"{persona['first']} {persona.get('middle', '')[:1]} {persona['last']}".replace('  ', ' ').strip()
    enriched_block = ''
    if enriched:
        enriched_block = f"""
Real specs about your car (looked up from public NHTSA records — useful if the site asks):
  Year/Make/Model/Trim: {enriched.get('year_make_model_trim', '')}
  Body class: {enriched.get('body_class', '')}
  Drive type: {enriched.get('drive_type', '')}
  Fuel: {enriched.get('fuel_type', '')}
  Engine: {enriched.get('engine', '')}
  Transmission: {enriched.get('transmission', '')}
  Doors / Seats: {enriched.get('doors', '')} / {enriched.get('seats', '')}
  Built at: {enriched.get('plant', '')}
  Standard safety features: {', '.join(enriched.get('safety_features', []))}
  Open recalls (you're aware of these but they're not affecting drivability): {len(enriched.get('open_recalls', []))} open
"""

    base = f"""You are roleplaying as {full_name} from {persona['city']}, {persona['state']}. You bought this car about {persona['years_owned']} years ago and you're standing in your driveway with a few minutes to spare, getting a quick trade-in quote before lunch. You know your car well — answer questions confidently and quickly. Don't dawdle, don't over-read; act like a real person who has done online shopping before.

You will complete an online car-selling flow and extract the offer amount.

Your full identity (use whatever the form asks for):
  Name: {full_name}
  Email: {persona['email']}
  Phone: {persona['phone']}
  Date of birth: {persona['dob']}
  Street address: {persona['street']}
  City / State / ZIP: {persona['city']}, {persona['state']} {zip_}
  Driver's license: {persona['dl_state']} #{persona['dl_number']}
  Employment: {persona['employment']}
  Years at address: {persona['years_at_address']}

Your car — use these EXACT facts in EVERY answer the site asks. If the site asks a question not listed here, pick the most conservative / cleanest option (no damage, no issues) and note in your final output what the question was and what you answered:
  VIN: {vin}
  Mileage: {true_mileage}
  ZIP: {zip_}  (state: {state})
  Condition: {condition}
  {facts_block}
{enriched_block}

CRITICAL: record every question the site asks and the answer you gave, in your final output's "answers_given" field. This is so we can verify you told identical facts to all three buyers.

**Act like a real shopper:**
  - You know your car. Don't over-deliberate — answer each question and move on. A real person standing at their car can knock out this whole flow in 3–5 minutes.
  - Read enough to answer correctly, then act. Don't read every paragraph aloud.
  - Scroll when you need to see what's below the fold; otherwise just answer what's visible.
  - If a captcha / "verify you are human" / Cloudflare challenge appears: WAIT, don't interact. Do NOT click the checkbox, do NOT click at coordinates inside the challenge widget. Real users wait 5–30 seconds and it auto-resolves. Clicking the box ESCALATES the challenge to a harder one. Instead, wait up to 120 seconds without interacting with the challenge widget itself (you can still scroll the rest of the page). If it still hasn't cleared, return status "site_blocked".

Defaults for ALL questions where the wizard asks for additional info — use these consistently so runs are comparable:
  Accidents: No
  Title status: Clean / free and clear
  Modifications: No modifications
  Ownership: Own outright (no loan, no lease)
  Number of keys: 2 or more
  Features / color / drivetrain: pick the FIRST / default option if unsure
  Email (if ever asked): caroffers.tool@gmail.com
  Phone (if ever asked): skip or use placeholder, but DO NOT proceed through an SMS verification step — stop and return "account_required" instead.

What success looks like:
  Reach a page showing a dollar-amount trade-in offer (e.g. "$18,500"). Extract that number.

Stop conditions (return immediately with the given status):
  - "account_required"  — site demands SMS verification, phone OTP, or account login before showing the offer.
  - "site_blocked"       — error modal like "Whoops", "Something went wrong", "Access denied", or Cloudflare challenge.
  - "error"              — stuck in a loop, cannot advance for 3+ steps, or page is unusable.
  - "ok" with offer_usd  — you reached the final offer page.

Return your final verdict as a JSON object on a line by itself (the harness parses the LAST JSON object in your output):
  {{"status": "ok"|"account_required"|"site_blocked"|"error",
    "offer_usd": <integer or null>,
    "final_url": "<current URL>",
    "notes": "<1-sentence summary of where the flow ended>",
    "answers_given": [
      {{"question": "<what the site asked, verbatim or close>", "answer": "<what you entered/selected>"}},
      ...
    ]}}

Do NOT fabricate an offer. If you don't see a dollar amount, status is not "ok".

Start URL: {START_URLS[site]}
"""

    site_hints = {
        'carvana': """
Carvana-specific notes:
  - The sell flow is at /sell-my-car. Click the main "Get My Offer" CTA to begin.
  - On the VIN-entry page you may see a radio toggle between "License Plate" and "VIN" — choose VIN.
  - You may need to pick a State from a dropdown even in VIN mode. Use: {state}.
  - After VIN submit, Carvana asks a series of vehicle-confirmation questions (color / trim / modifications / accidents / title / ownership / keys). Answer using the defaults above.
  - The final offer page shows a large dollar amount. Extract that as offer_usd.
""",
        'carmax': """
CarMax-specific notes:
  - The sell flow is at /sell-my-car. There is a hero VIN-entry form on the landing page itself.
  - After VIN submit you land on an "offers" page with an offer ID in the URL (like /sell-my-car/offers/XXX).
  - You may need to click "Continue" or an "ico-continue-button" to reach /appraisal-checkout.
  - On /appraisal-checkout, a series of radio-group questions appear — the page uses a sidebar "Next" button that stays DISABLED until all required answers are provided. Answer each group using the defaults above.
  - Some fields may be <select> dropdowns (especially "payments" or "title"). Pick the default/clean option.
  - CarMax may require an email but should NOT require SMS. If it does, return "account_required".
  - Final offer shows a dollar amount + expiration date.
""",
        'driveway': """
Driveway-specific notes:
  - Start URL is https://www.driveway.com/sell-your-car (the shorter /sell 404s).
  - The landing page has a tab for VIN vs License Plate — choose VIN.
  - After clicking the "Get an Offer" button, Driveway sometimes shows a "Whoops! Something went wrong" modal — that's a bot-detection signal. If you see this, return "site_blocked" immediately.
  - If the flow proceeds, it asks mileage, condition, contact email, then shows the offer.
""",
    }
    return base + site_hints[site].format(state=state)


async def run(args):
    log_dir = LOG_ROOT / f"{args.site}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Per-site persistent profile — copy the seeded consumer profile once if
    # one exists. Avoids the SingletonLock contention with the main service.
    profile_dir = HERE / 'profiles' / args.profile
    profile_dir.parent.mkdir(exist_ok=True)
    if not profile_dir.exists():
        src = pathlib.Path(f'/opt/car-offers-preview/.chrome-profiles/cons{args.consumer:02d}')
        if src.exists():
            shutil.copytree(src, profile_dir)
            # Strip stale lock files from the copy.
            for n in ('SingletonLock', 'SingletonCookie', 'SingletonSocket'):
                (profile_dir / n).unlink(missing_ok=True)
        else:
            profile_dir.mkdir()

    # Decodo sticky-session proxy URL, geo-targeted to the consumer's ZIP.
    proxy_user = os.environ.get('PROXY_USER', 'spjax0kgms')
    proxy_pass = os.environ.get('PROXY_PASS', '')
    proxy_host = os.environ.get('PROXY_HOST', 'gate.decodo.com')
    proxy_port = os.environ.get('PROXY_PORT', '10001')
    proxy_auth = f"user-{proxy_user}-country-us-zip-{args.zip}-session-{args.session_id}-sessionduration-1440"
    proxy_url = f"http://{proxy_auth}:{proxy_pass}@{proxy_host}:{proxy_port}"

    os.environ['DISPLAY'] = args.display

    chromium_args = [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-blink-features=AutomationControlled',
        '--window-size=1920,1080',
        '--lang=en-US',
        '--webrtc-ip-handling-policy=disable_non_proxied_udp',
    ]

    profile = BrowserProfile(
        headless=False,
        args=chromium_args,
        user_data_dir=str(profile_dir),
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        keep_alive=False,
        proxy=ProxySettings(
            server=f'http://{proxy_host}:{proxy_port}',
            username=proxy_auth,
            password=proxy_pass,
        ),
    )

    session = BrowserSession(browser_profile=profile, is_local=True)

    # Write proxy auth via a context init (Chromium doesn't take auth on the --proxy-server arg)
    async def on_context(ctx):
        # Set proxy auth header
        await ctx.set_extra_http_headers({'Accept-Language': 'en-US,en;q=0.9'})
        await ctx.add_init_script(STEALTH_INIT)
        # Chromium receives proxy auth via navigator.registerProtocolHandler or basic auth prompt;
        # simplest path: inject via page.auth when needed. browser-use handles basic-auth prompt automatically.

    # We'll add the stealth init script after the session starts.
    (log_dir / 'task_prompt.txt').write_text(task_prompt(args.site, args.vin, args.mileage, args.zip, args.condition))

    llm = ChatAnthropic(model='claude-sonnet-4-5-20250929', temperature=0.0, api_key=os.environ['ANTHROPIC_API_KEY'])

    agent = Agent(
        task=task_prompt(args.site, args.vin, args.mileage, args.zip, args.condition),
        llm=llm,
        browser_session=session,
        use_vision=True,
        max_actions_per_step=3,
        save_conversation_path=str(log_dir / 'conversation'),
    )

    start = time.time()
    err = None
    history = None
    try:
        history = await agent.run(max_steps=args.max_steps)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"

    duration = time.time() - start

    # Extract final JSON verdict from history.final_result() if available.
    verdict = None
    final_text = ''
    if history:
        try:
            final_text = history.final_result() or ''
        except Exception:
            pass
    if final_text:
        m = re.findall(r'\{[^{}]*"status"[^{}]*\}', final_text, re.DOTALL)
        if m:
            try:
                verdict = json.loads(m[-1])
            except Exception:
                pass

    result = {
        'site': args.site,
        'vin': args.vin,
        'mileage': args.mileage,
        'zip': args.zip,
        'display': args.display,
        'session_id': args.session_id,
        'duration_s': round(duration, 1),
        'error': err,
        'verdict': verdict,
        'final_text': final_text[:2000] if final_text else None,
    }
    (log_dir / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

    try:
        await session.stop()
    except Exception:
        pass

    return 0 if verdict and verdict.get('status') == 'ok' else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--site', required=True, choices=list(START_URLS.keys()))
    p.add_argument('--vin', required=True)
    p.add_argument('--mileage', type=int, required=True)
    p.add_argument('--zip', required=True)
    p.add_argument('--condition', default='Good')
    p.add_argument('--display', default=':100')
    p.add_argument('--profile', default='llmnav')
    p.add_argument('--session-id', default='llmnav-session')
    p.add_argument('--consumer', type=int, default=1)
    p.add_argument('--max-steps', type=int, default=40)
    args = p.parse_args()
    sys.exit(asyncio.run(run(args)))
