"""Chain classification using Claude API."""

import json
import re
from datetime import date, datetime, timedelta

import anthropic
import httpx

from db import COUNTRY_NAMES, get_connection, get_db, init_db, setup_logging

logger = setup_logging("classify")

MODEL = "claude-sonnet-4-20250514"

# Chains with fewer locations are overwhelmingly independent gyms or OSM
# tagging noise — classifying them wastes API spend and adds no competitive
# signal. Raise/lower to widen or narrow the classified chain universe.
MIN_LOCATIONS_FOR_CLASSIFICATION = 4

# Pricing for claude-sonnet-4 (USD per million tokens).
COST_PER_MTOK_INPUT = 3.0
COST_PER_MTOK_OUTPUT = 15.0

# Generic sports-facility words that OSM contributors use as a "name" but
# which don't actually refer to a branded chain. Matched case-insensitively
# on the full canonical_name (NOT substring — "The Gym" is ambiguous and
# must still go to Claude).
OSM_GENERIC_NAMES = {
    "sporthalle", "turnhalle", "sporthal", "gimnasio", "poliesportiu",
    "fitness", "gym", "sports centre", "sports center", "salle de sport",
    "palestra", "polideportivo",
}


def get_chains_to_classify(conn) -> list[dict]:
    """Get chains that need classification or reclassification."""
    cutoff = (datetime.now() - timedelta(days=90)).date().isoformat()

    rows = conn.execute("""
        SELECT c.id, c.canonical_name, c.competitive_classification,
               c.location_count, c.manually_reviewed, c.last_classified_date
        FROM chains c
        WHERE c.manually_reviewed = 0
          AND c.location_count >= ?
          AND (c.competitive_classification = 'unknown'
               OR c.last_classified_date IS NULL
               OR c.last_classified_date < ?)
        ORDER BY c.location_count DESC
    """, (MIN_LOCATIONS_FOR_CLASSIFICATION, cutoff)).fetchall()

    return [dict(r) for r in rows]


def get_chain_context(conn, chain_id: int, chain_name: str) -> dict:
    """Gather context about a chain for the classification prompt."""
    # Countries and counts
    country_rows = conn.execute("""
        SELECT country, COUNT(*) as cnt
        FROM locations
        WHERE chain_id = ? AND active = 1
        GROUP BY country
    """, (chain_id,)).fetchall()

    countries = {COUNTRY_NAMES.get(r["country"], r["country"]): r["cnt"] for r in country_rows}

    # Sample cities
    city_rows = conn.execute("""
        SELECT DISTINCT city FROM locations
        WHERE chain_id = ? AND active = 1 AND city IS NOT NULL
        LIMIT 10
    """, (chain_id,)).fetchall()
    cities = [r["city"] for r in city_rows]

    # Websites
    web_row = conn.execute("""
        SELECT website FROM locations
        WHERE chain_id = ? AND website IS NOT NULL AND website != ''
        LIMIT 1
    """, (chain_id,)).fetchone()
    website = web_row["website"] if web_row else None

    # Informative OSM tags sample
    tag_row = conn.execute("""
        SELECT osm_tags FROM locations
        WHERE chain_id = ? AND active = 1 AND osm_tags IS NOT NULL
        LIMIT 1
    """, (chain_id,)).fetchone()

    informative_tags = {}
    if tag_row:
        try:
            tags = json.loads(tag_row["osm_tags"])
            for key in ["fee", "sport", "opening_hours", "membership", "description"]:
                if key in tags:
                    informative_tags[key] = tags[key]
        except json.JSONDecodeError:
            pass

    total_locations = sum(r["cnt"] for r in country_rows)

    return {
        "chain_name": chain_name,
        "countries": countries,
        "total_locations": total_locations,
        "sample_cities": cities,
        "website": website,
        "osm_tags": informative_tags,
    }


def fetch_website_pricing(url: str) -> str | None:
    """Try to fetch pricing page content from a chain's website."""
    if not url:
        return None

    # Try common pricing page paths
    base = url.rstrip("/")
    paths = [
        "",
        "/pricing",
        "/prices",
        "/tarifs",
        "/precios",
        "/abonnement",
        "/membership",
        "/prijzen",
    ]

    for path in paths:
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(base + path, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    text = resp.text
                    # Strip HTML to get text content (rough extraction)
                    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    # Limit to 3000 chars
                    if len(text) > 3000:
                        text = text[:3000]
                    if "price" in text.lower() or "euro" in text.lower() or "€" in text or "tarif" in text.lower() or "precio" in text.lower():
                        return text
        except Exception:
            continue

    return None


def classify_chain(client: anthropic.Anthropic, context: dict, pricing_page: str | None = None) -> dict:
    """Call Claude to classify a chain."""
    pricing_context = ""
    if pricing_page:
        pricing_context = f"\n\nWebsite pricing page content:\n{pricing_page}\n"

    prompt = f"""You are a fitness industry analyst. Classify this gym chain for a competitive analysis focused on Basic-Fit, the European budget gym operator.

Chain: {context['chain_name']}
Countries present: {json.dumps(context['countries'])}
Total locations: {context['total_locations']}
Sample cities: {', '.join(context['sample_cities']) if context['sample_cities'] else 'N/A'}
Website: {context['website'] or 'N/A'}
OSM tags: {json.dumps(context['osm_tags']) if context['osm_tags'] else 'N/A'}
{pricing_context}

Classification rules:
- direct_competitor: Gym chains that compete with Basic-Fit for similar customers (budget to mid-market, high-volume, multiple locations). This includes other budget/value gym chains, large mid-market chains with significant overlap in target demographics.
- non_competitor: Premium-only clubs, boutique studios (yoga, pilates, CrossFit boxes, martial arts), hotel gyms, municipal sports centers, personal training studios, or chains so small/niche they don't compete for the same customer base.
- unknown: Cannot determine with reasonable confidence.

Price tier guidance:
- budget: under €25/month standard membership
- mid_market: €25-50/month
- premium: over €50/month

For the normalized 18-month cost: estimate total cost for someone who joins and stays 18 months (joining fee amortized over 18 months + 18 months of membership). Basic-Fit's all-in 18-month cost is approximately €300-360 for reference.

Return ONLY valid JSON (no markdown fences) with these exact fields:
{{
  "competitive_classification": "direct_competitor" | "non_competitor" | "unknown",
  "price_tier": "budget" | "mid_market" | "premium" | "unknown",
  "normalized_18mo_cost": <number or null>,
  "membership_model": "commitment" | "flexible" | "mixed" | "unknown",
  "pricing_notes": "<brief notes on pricing>",
  "rationale": "<one paragraph explaining the classification>"
}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    # Try to extract JSON from the response
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse classification response: {text}")


def run_classification(progress_cb=None):
    """Run the classification pipeline."""
    def log(msg):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    init_db()
    client = anthropic.Anthropic()

    with get_db() as conn:
        chains = get_chains_to_classify(conn)
        log(f"Found {len(chains)} chains to classify")

        for i, chain in enumerate(chains, 1):
            chain_id = chain["id"]
            chain_name = chain["canonical_name"]
            location_count = chain["location_count"]

            log(f"Classifying ({i}/{len(chains)}): {chain_name} ({location_count} locations)")

            try:
                context = get_chain_context(conn, chain_id, chain_name)

                # For larger chains, try to fetch website pricing
                pricing_page = None
                if location_count >= 10 and context["website"]:
                    logger.info("Fetching pricing page for %s", chain_name)
                    pricing_page = fetch_website_pricing(context["website"])
                    if pricing_page:
                        logger.info("Got pricing page content (%d chars)", len(pricing_page))

                result = classify_chain(client, context, pricing_page)

                conn.execute("""
                    UPDATE chains SET
                        competitive_classification = ?,
                        price_tier = ?,
                        normalized_18mo_cost = ?,
                        membership_model = ?,
                        pricing_notes = ?,
                        ai_classification_rationale = ?,
                        last_classified_date = ?
                    WHERE id = ?
                """, (
                    result.get("competitive_classification", "unknown"),
                    result.get("price_tier", "unknown"),
                    result.get("normalized_18mo_cost"),
                    result.get("membership_model", "unknown"),
                    result.get("pricing_notes"),
                    result.get("rationale"),
                    date.today().isoformat(),
                    chain_id,
                ))

                log(f"  → {chain_name}: {result.get('competitive_classification')} ({result.get('price_tier')} tier)")

            except Exception as e:
                log(f"  → {chain_name}: FAILED — {e}")

    log("Classification complete")


def _extract_text_from_response(response) -> str:
    """Walk content blocks of a web_search-enabled response and return the
    final text block. The response shape is a list of blocks; tool_use and
    tool_result blocks are intermixed, but the final answer is always the
    last `text` block."""
    final_text = ""
    for block in response.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            final_text = getattr(block, "text", "") or final_text
    return (final_text or "").strip()


def _parse_json_body(text: str) -> dict:
    """Parse JSON from a model response, tolerating markdown fences."""
    s = text.strip()
    # Strip ```json ... ``` fences if present.
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(f"Could not parse classification response: {text[:500]}")


def classify_chain_v2(client: anthropic.Anthropic, context: dict) -> tuple[dict, int, int]:
    """Call Claude with web_search enabled to classify a chain.

    Returns (parsed_json, input_tokens, output_tokens).
    """
    prompt = f"""You are a fitness industry analyst. Classify this gym chain for a competitive analysis focused on Basic-Fit, the European budget gym operator (18-month all-in cost ~€300-360).

Chain: {context['chain_name']}
Countries present: {json.dumps(context['countries'])}
Total locations: {context['total_locations']}
Sample cities: {', '.join(context['sample_cities']) if context['sample_cities'] else 'N/A'}
Known website: {context['website'] or 'none — you must search'}

Use web_search to find the chain's actual website, pricing, and membership model. Look for: official site, pricing/tarifs/prix/precios page, news coverage that mentions it as municipal vs private.

## Competitive rules (updated)
- direct_competitor: competes with Basic-Fit for the same customer. Private OR public. Includes:
  - Budget and mid-market private chains (multi-location, high-volume).
  - Municipal/public facilities IF they offer an individual gym membership (not just pay-per-entry, not just pool/lane rental, not just team sports) AND the monthly price is under €50.
- non_competitor: premium-only clubs (>€50/mo, boutique positioning), single-discipline studios (yoga/pilates/CrossFit/martial arts), hotel gyms, municipal facilities that only offer pay-per-entry / pool / team sports, personal training studios, medical/physio rehab centres.
- not_a_chain: OSM tag noise (generic words like "Sporthalle" being treated as a chain name because many OSM entries share that label), or a set of unrelated single-owner gyms that happen to have the same generic name.
- unknown: web search returned nothing conclusive after a genuine attempt.

## Ownership rules
- private: privately-owned / franchise / corporate chain.
- public: municipal, state-owned, university-owned, or government-funded facility.
- unknown: unclear after search.

## Price tier (unchanged)
- budget: under €25/mo
- mid_market: €25-50/mo
- premium: over €50/mo

Return ONLY JSON (no markdown fences) with these fields:
{{
  "competitive_classification": "direct_competitor" | "non_competitor" | "not_a_chain" | "unknown",
  "ownership_type": "private" | "public" | "unknown",
  "price_tier": "budget" | "mid_market" | "premium" | "unknown",
  "normalized_18mo_cost": <number or null>,
  "membership_model": "commitment" | "flexible" | "mixed" | "unknown",
  "pricing_notes": "<brief>",
  "rationale": "<one paragraph — cite what web search found>"
}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        messages=[{"role": "user", "content": prompt}],
    )

    text = _extract_text_from_response(response)
    parsed = _parse_json_body(text)

    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) or 0
    out_tok = getattr(usage, "output_tokens", 0) or 0
    return parsed, in_tok, out_tok


def _unknown_chains_to_reclassify(conn) -> list[dict]:
    """All chains currently stuck at 'unknown' that are big enough to bother with."""
    rows = conn.execute("""
        SELECT id, canonical_name, location_count
        FROM chains
        WHERE competitive_classification = 'unknown'
          AND location_count >= ?
          AND manually_reviewed = 0
        ORDER BY location_count DESC
    """, (MIN_LOCATIONS_FOR_CLASSIFICATION,)).fetchall()
    return [dict(r) for r in rows]


def reclassify_unknown(conn, client, progress_cb=None, dry_run: bool = False) -> dict:
    """Second-pass classification for chains still labelled 'unknown'.

    Uses web_search via Claude to disambiguate real chains from OSM generic
    terms. OSM generics (see OSM_GENERIC_NAMES) short-circuit to 'not_a_chain'
    with no API call.

    Returns a stats dict.
    """
    def log(msg):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    chains = _unknown_chains_to_reclassify(conn)
    log(f"Reclassify: {len(chains)} unknown chains with >= {MIN_LOCATIONS_FOR_CLASSIFICATION} locations")

    if dry_run:
        return {
            "dry_run": True,
            "chains_planned": len(chains),
            "osm_generics_would_skip": sum(
                1 for c in chains
                if c["canonical_name"].strip().lower() in OSM_GENERIC_NAMES
            ),
            "plan": [
                {
                    "id": c["id"],
                    "canonical_name": c["canonical_name"],
                    "location_count": c["location_count"],
                    "action": (
                        "mark_not_a_chain"
                        if c["canonical_name"].strip().lower() in OSM_GENERIC_NAMES
                        else "call_claude_with_websearch"
                    ),
                }
                for c in chains
            ],
        }

    stats = {
        "chains_reclassified": 0,
        "osm_generics_filtered": 0,
        "tokens_input": 0,
        "tokens_output": 0,
        "api_calls": 0,
        "cost_usd": 0.0,
        "by_classification": {},
        "failures": 0,
    }
    today = date.today().isoformat()

    for i, chain in enumerate(chains, 1):
        chain_id = chain["id"]
        name = chain["canonical_name"]
        key = name.strip().lower()

        # --- 1) OSM generic short-circuit ---
        if key in OSM_GENERIC_NAMES:
            conn.execute("""
                UPDATE chains SET
                    competitive_classification = 'not_a_chain',
                    ownership_type = 'unknown',
                    ai_classification_rationale = ?,
                    last_classified_date = ?
                WHERE id = ?
            """, ("OSM generic term, not a branded chain", today, chain_id))
            conn.commit()
            stats["osm_generics_filtered"] += 1
            stats["chains_reclassified"] += 1
            stats["by_classification"]["not_a_chain"] = \
                stats["by_classification"].get("not_a_chain", 0) + 1
            log(f"  ({i}/{len(chains)}) {name}: OSM generic -> not_a_chain")
            continue

        # --- 2) Claude with web_search ---
        try:
            context = get_chain_context(conn, chain_id, name)
            result, in_tok, out_tok = classify_chain_v2(client, context)
            stats["api_calls"] += 1
            stats["tokens_input"] += in_tok
            stats["tokens_output"] += out_tok

            classification = result.get("competitive_classification", "unknown")
            conn.execute("""
                UPDATE chains SET
                    competitive_classification = ?,
                    price_tier = ?,
                    normalized_18mo_cost = ?,
                    membership_model = ?,
                    pricing_notes = ?,
                    ai_classification_rationale = ?,
                    ownership_type = ?,
                    last_classified_date = ?
                WHERE id = ?
            """, (
                classification,
                result.get("price_tier", "unknown"),
                result.get("normalized_18mo_cost"),
                result.get("membership_model", "unknown"),
                result.get("pricing_notes"),
                result.get("rationale"),
                result.get("ownership_type", "unknown"),
                today,
                chain_id,
            ))
            conn.commit()

            stats["chains_reclassified"] += 1
            stats["by_classification"][classification] = \
                stats["by_classification"].get(classification, 0) + 1
            log(f"  ({i}/{len(chains)}) {name}: {classification} ({result.get('ownership_type', 'unknown')}, {result.get('price_tier', 'unknown')})")
        except Exception as e:
            stats["failures"] += 1
            log(f"  ({i}/{len(chains)}) {name}: FAILED — {e}")

    stats["cost_usd"] = round(
        stats["tokens_input"] / 1_000_000 * COST_PER_MTOK_INPUT
        + stats["tokens_output"] / 1_000_000 * COST_PER_MTOK_OUTPUT,
        4,
    )
    log(
        f"Reclassify done: {stats['chains_reclassified']} updated, "
        f"{stats['osm_generics_filtered']} OSM generics, "
        f"{stats['api_calls']} Claude calls, "
        f"${stats['cost_usd']:.2f} spent"
    )
    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Chain classifier")
    parser.add_argument(
        "--reclassify-unknown",
        action="store_true",
        help="Re-run classification on chains stuck at 'unknown' using web_search.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --reclassify-unknown, print the plan instead of calling Claude.",
    )
    args = parser.parse_args()

    if args.reclassify_unknown:
        init_db()
        client = anthropic.Anthropic() if not args.dry_run else None
        conn = get_connection()
        try:
            stats = reclassify_unknown(conn, client, dry_run=args.dry_run)
        finally:
            conn.close()
        print(json.dumps(stats, indent=2, default=str))
    else:
        run_classification()
