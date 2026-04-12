"""Chain classification using Claude API."""

import json
import re
from datetime import date, datetime, timedelta

import anthropic
import httpx

from db import COUNTRY_NAMES, get_db, init_db, setup_logging

logger = setup_logging("classify")

MODEL = "claude-sonnet-4-20250514"

# Chains with fewer locations are overwhelmingly independent gyms or OSM
# tagging noise — classifying them wastes API spend and adds no competitive
# signal. Raise/lower to widen or narrow the classified chain universe.
MIN_LOCATIONS_FOR_CLASSIFICATION = 4


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


if __name__ == "__main__":
    run_classification()
