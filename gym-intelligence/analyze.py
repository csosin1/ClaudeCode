"""Quarterly competitive analysis generation using Claude."""

import json
from datetime import date, timedelta

import anthropic

from db import COUNTRY_NAMES, get_db, init_db, setup_logging

logger = setup_logging("analyze")

MODEL = "claude-sonnet-4-20250514"


def get_current_snapshot(conn) -> dict:
    """Get the most recent snapshot data."""
    # Find the most recent snapshot date
    row = conn.execute("SELECT MAX(snapshot_date) as d FROM snapshots").fetchone()
    if not row or not row["d"]:
        return {}

    current_date = row["d"]

    rows = conn.execute("""
        SELECT s.country, c.canonical_name, c.competitive_classification,
               c.price_tier, c.normalized_18mo_cost, s.location_count
        FROM snapshots s
        JOIN chains c ON s.chain_id = c.id
        WHERE s.snapshot_date = ?
        ORDER BY s.country, s.location_count DESC
    """, (current_date,)).fetchall()

    result = {"date": current_date, "data": [dict(r) for r in rows]}
    return result


def get_previous_snapshot(conn) -> dict:
    """Get the second most recent snapshot data."""
    rows = conn.execute("""
        SELECT DISTINCT snapshot_date FROM snapshots
        ORDER BY snapshot_date DESC
        LIMIT 2
    """).fetchall()

    if len(rows) < 2:
        return {}

    prev_date = rows[1]["snapshot_date"]

    data_rows = conn.execute("""
        SELECT s.country, c.canonical_name, c.competitive_classification,
               c.price_tier, s.location_count
        FROM snapshots s
        JOIN chains c ON s.chain_id = c.id
        WHERE s.snapshot_date = ?
        ORDER BY s.country, s.location_count DESC
    """, (prev_date,)).fetchall()

    return {"date": prev_date, "data": [dict(r) for r in data_rows]}


def get_chain_classifications(conn) -> list[dict]:
    """Get all chain classifications."""
    rows = conn.execute("""
        SELECT canonical_name, competitive_classification, price_tier,
               normalized_18mo_cost, membership_model, location_count,
               pricing_notes, ai_classification_rationale
        FROM chains
        WHERE location_count > 0
        ORDER BY location_count DESC
    """).fetchall()

    return [dict(r) for r in rows]


def get_basicfit_context(conn) -> dict:
    """Get Basic-Fit specific metrics."""
    row = conn.execute("""
        SELECT c.id, c.location_count
        FROM chains c
        WHERE LOWER(c.canonical_name) = 'basic-fit'
    """).fetchone()

    if not row:
        return {"total_locations": 0, "by_country": {}}

    country_rows = conn.execute("""
        SELECT country, COUNT(*) as cnt
        FROM locations
        WHERE chain_id = ? AND active = 1
        GROUP BY country
    """, (row["id"],)).fetchall()

    return {
        "total_locations": row["location_count"],
        "by_country": {
            COUNTRY_NAMES.get(r["country"], r["country"]): r["cnt"]
            for r in country_rows
        },
    }


def generate_analysis(
    client: anthropic.Anthropic,
    current: dict,
    previous: dict,
    classifications: list[dict],
    basicfit: dict,
) -> str:
    """Generate the quarterly competitive analysis."""

    prompt = f"""You are a senior equity research analyst covering the European fitness industry. Produce a quarterly competitive landscape report for Basic-Fit investors.

## Current Quarter Snapshot ({current.get('date', 'N/A')})
{json.dumps(current.get('data', []), indent=2)}

## Previous Quarter Snapshot ({previous.get('date', 'N/A')})
{json.dumps(previous.get('data', []), indent=2) if previous else 'No previous quarter data available.'}

## Chain Classifications
{json.dumps(classifications, indent=2)}

## Basic-Fit Context
Total locations: {basicfit['total_locations']}
By country: {json.dumps(basicfit['by_country'])}

---

Produce a markdown report with the following sections:

# Quarterly Competitive Landscape Report

## 1. Overall Market Structure
How concentrated is the budget gym market in each country? What is Basic-Fit's estimated market share among direct competitors in each country? Present as a brief table and narrative.

## 2. Chains on the Rise
Any direct competitor growing >10% quarter-over-quarter in any country. If no previous quarter data, note this and instead highlight the largest competitors by country.

## 3. Chains in Decline
Any direct competitor shrinking >10% QoQ. If no previous data, note this.

## 4. New Entrants
Any chain that appeared this quarter with 3+ locations that was not in the previous quarter.

## 5. Country-by-Country Narrative
One paragraph per country on the competitive situation, referencing specific chains and their positioning.

## 6. Overall Threat Assessment
A summary paragraph with a qualitative threat level (low / moderate / elevated / high) for Basic-Fit's competitive position, with specific reasoning.

Be specific and data-driven. Reference actual chain names and location counts. If data is limited for the first run, note the baseline nature of this report. Write in a professional equity research tone."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text


def run_analysis(progress_cb=None):
    """Run the quarterly analysis pipeline."""
    def log(msg):
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    init_db()
    client = anthropic.Anthropic()

    with get_db() as conn:
        current = get_current_snapshot(conn)
        if not current.get("data"):
            log("No snapshot data found. Run collection first.")
            return

        previous = get_previous_snapshot(conn)
        classifications = get_chain_classifications(conn)
        basicfit = get_basicfit_context(conn)

        log(f"Generating analysis: {len(current.get('data', []))} entries, {len(classifications)} chains")
        log("Calling Claude for competitive report (this may take 30-60s)...")

        analysis = generate_analysis(client, current, previous, classifications, basicfit)

        conn.execute(
            "INSERT INTO quarterly_analyses (analysis_date, analysis_text, model_used) VALUES (?, ?, ?)",
            (date.today().isoformat(), analysis, MODEL),
        )

        log(f"Analysis stored ({len(analysis)} chars)")


if __name__ == "__main__":
    run_analysis()
