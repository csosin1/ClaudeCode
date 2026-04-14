#!/usr/bin/env python3
"""
Free public VIN enrichment.

Pulls together everything we can learn about a VIN from free public sources
and writes to `enrichment/<vin>.json`. The harness reads from this cache when
building CAR_FACTS for a consumer, so all three dealers hear the same story.

Sources used:
  1. NHTSA vPIC full decode (vpic.nhtsa.dot.gov) — all 150+ decoded fields
  2. NHTSA Recalls API (api.nhtsa.gov) — open-recall campaigns for this VIN
  3. EPA fuel economy (fueleconomy.gov web service) — by year/make/model/trim
  4. Google VIN search — top 3 public result snippets (past listings, photos)

Runs fully offline after first API call — aggressive caching.
"""

import argparse, json, pathlib, re, sys, time, urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).parent
CACHE = HERE / 'enrichment'
CACHE.mkdir(exist_ok=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'


def http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


def vpic_decode(vin: str) -> dict:
    """NHTSA vPIC full decode — ~150 fields, free, no key."""
    url = f'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json'
    data = json.loads(http_get(url))
    if not data.get('Results'):
        return {}
    out = {k: v for k, v in data['Results'][0].items() if v and v not in ('Not Applicable', '0')}
    return out


def nhtsa_recalls(vin: str) -> list:
    """Open recall campaigns for this specific VIN. Free."""
    url = f'https://api.nhtsa.gov/recalls/recallsByVehicle?make=&model=&modelYear=&vin={vin}'
    try:
        data = json.loads(http_get(url))
        return data.get('results', [])
    except Exception:
        return []


def nhtsa_recalls_by_model(year: str, make: str, model: str) -> list:
    """Model-level recalls (fallback; more hits than per-VIN)."""
    url = (f'https://api.nhtsa.gov/recalls/recallsByVehicle?'
           f'make={urllib.parse.quote(make)}&model={urllib.parse.quote(model)}&modelYear={year}')
    try:
        data = json.loads(http_get(url))
        return data.get('results', [])[:5]
    except Exception:
        return []


def epa_fuel_economy(year: str, make: str, model: str) -> list:
    """EPA fuel-economy records matching year/make/model. Gives MPG, fuel grade, transmission variants."""
    url = (f'https://fueleconomy.gov/ws/rest/vehicle/menu/options?'
           f'year={year}&make={urllib.parse.quote(make)}&model={urllib.parse.quote(model)}')
    try:
        xml = http_get(url)
    except Exception:
        return []
    # Minimal XML parse without deps: extract <value>N</value> entries
    ids = re.findall(r'<value>(\d+)</value>', xml)
    results = []
    for vid in ids[:5]:
        try:
            detail_xml = http_get(f'https://fueleconomy.gov/ws/rest/vehicle/{vid}')
            def tag(t):
                m = re.search(rf'<{t}>([^<]*)</{t}>', detail_xml)
                return m.group(1) if m else ''
            results.append({
                'id': vid,
                'trany': tag('trany'),
                'drive': tag('drive'),
                'fuelType': tag('fuelType'),
                'city08': tag('city08'),
                'highway08': tag('highway08'),
                'comb08': tag('comb08'),
                'cylinders': tag('cylinders'),
                'displ': tag('displ'),
                'VClass': tag('VClass'),
            })
        except Exception:
            continue
    return results


def google_vin_search(vin: str) -> list:
    """Top DuckDuckGo HTML results for the VIN — surfaces past listings / photos."""
    try:
        # DuckDuckGo HTML is more scrapeable than Google and has no captchas
        url = f'https://html.duckduckgo.com/html/?q={urllib.parse.quote(vin)}'
        html = http_get(url)
        # Extract result title + snippet + url
        results = []
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>[\s\S]*?<a[^>]+class="result__snippet"[^>]*>([^<]+)</a>', html):
            href, title, snippet = m.group(1), m.group(2), m.group(3)
            # Clean DDG redirect wrapping
            href = re.sub(r'^//duckduckgo\.com/l/\?uddg=', '', href)
            href = urllib.parse.unquote(href.split('&')[0])
            results.append({'title': title.strip(), 'url': href, 'snippet': re.sub(r'\s+', ' ', snippet).strip()})
            if len(results) >= 5:
                break
        return results
    except Exception:
        return []


def summarize_for_prompt(vin: str, v: dict, recalls: list, epa: list, web: list) -> dict:
    """Distill the enrichment into the shape run_site.py's CAR_FACTS uses."""
    cyl = v.get('EngineCylinders', '')
    disp = v.get('DisplacementL', '')
    hp = v.get('EngineHP', '')
    engine_desc = ''
    if cyl and disp:
        engine_desc = f'{disp}L {cyl}-cylinder'
        if hp: engine_desc += f' {hp}hp'

    trans = v.get('TransmissionStyle', '')
    speeds = v.get('TransmissionSpeeds', '')
    trans_desc = f'{speeds}-speed {trans}'.strip() if speeds and trans else trans

    safety_feats = [
        'Adaptive Cruise Control' if v.get('AdaptiveCruiseControl') == 'Standard' else None,
        'Lane Keep' if v.get('LaneKeepSystem') == 'Standard' else None,
        'Lane Departure Warning' if v.get('LaneDepartureWarning') == 'Standard' else None,
        'Blind Spot Warning' if v.get('BlindSpotWarning') in ('Standard', 'Optional') else None,
        'Stability Control' if v.get('ElectronicStabilityControl') == 'Standard' else None,
        'Traction Control' if v.get('TractionControl') == 'Standard' else None,
    ]
    safety_feats = [s for s in safety_feats if s]

    return {
        'vin': vin,
        'year_make_model_trim': f"{v.get('ModelYear', '')} {v.get('Make', '').title()} {v.get('Model', '')} {v.get('Trim', '')}".strip(),
        'body_class': v.get('BodyClass', ''),
        'vehicle_type': v.get('VehicleType', ''),
        'drive_type': v.get('DriveType', ''),  # "4x2" = FWD/RWD, "4x4/4-Wheel Drive" = AWD/4WD
        'fuel_type': v.get('FuelTypePrimary', ''),
        'engine': engine_desc,
        'transmission': trans_desc,
        'doors': v.get('Doors', ''),
        'seats': v.get('Seats', ''),
        'plant': f"{v.get('PlantCity', '').title()}, {v.get('PlantState', '')}, {v.get('PlantCountry', '').title()}".strip(', '),
        'manufacturer': v.get('Manufacturer', '').title(),
        'gvwr': v.get('GVWR', ''),
        'safety_features': safety_feats,
        'open_recalls': [
            {'campaign': r.get('NHTSACampaignNumber', ''), 'component': r.get('Component', ''), 'summary': r.get('Summary', '')[:200]}
            for r in recalls[:5]
        ],
        'mpg_options': [
            f"{e['trany']} / {e['drive']} / {e['city08']}/{e['highway08']} MPG city/hwy"
            for e in epa if e.get('trany')
        ][:3],
        'public_mentions': [
            {'title': w['title'][:120], 'url': w['url'], 'snippet': w['snippet'][:200]}
            for w in web[:5]
        ],
    }


def enrich(vin: str, force: bool = False) -> dict:
    """Full enrichment for one VIN. Cached in enrichment/<vin>.json."""
    cache_file = CACHE / f'{vin}.json'
    if cache_file.exists() and not force:
        return json.loads(cache_file.read_text())

    print(f'  enriching {vin}...', flush=True)
    v = vpic_decode(vin)
    time.sleep(0.3)
    recalls = nhtsa_recalls(vin)
    if not recalls and v.get('ModelYear') and v.get('Make') and v.get('Model'):
        recalls = nhtsa_recalls_by_model(v['ModelYear'], v['Make'], v['Model'])
    time.sleep(0.3)
    epa = epa_fuel_economy(v.get('ModelYear', ''), v.get('Make', ''), v.get('Model', ''))
    time.sleep(0.3)
    web = google_vin_search(vin)

    summary = summarize_for_prompt(vin, v, recalls, epa, web)
    payload = {'summary': summary, 'raw_vpic': v, 'raw_recalls': recalls, 'raw_epa': epa, 'raw_web': web}
    cache_file.write_text(json.dumps(payload, indent=2))
    return payload


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('vins', nargs='+', help='VINs to enrich')
    p.add_argument('--force', action='store_true')
    args = p.parse_args()
    for vin in args.vins:
        r = enrich(vin, force=args.force)
        print(json.dumps(r['summary'], indent=2))
        print('---')
