"""Narrative-only Claude extraction.

Two public entry points:
  - `locate_sections(html)` — split an EDGAR filing HTML/text into the
    subset of named sections (delinquency, fico, vintage,
    management_commentary) present in the filing. Returns
    {section_name: excerpt_text}, each excerpt stripped of tags and capped
    at settings.NARRATIVE_EXCERPT_CHAR_LIMIT chars.
  - `extract_from_sections(client, ticker, filing_type, period_end, sections)`
    — one Claude call per section, each asking ONLY for the fields that
    section could reasonably cover. Returns a merged dict of extracted
    fields + a cost dict with per-call input/output tokens.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import settings  # noqa: E402
from pipeline.metric_schema import METRIC_SCHEMA  # noqa: E402

log = logging.getLogger("narrative_extract")


# ---------------------------------------------------------------------------
# HTML / text prep
# ---------------------------------------------------------------------------


def _strip_html(raw: str) -> str:
    raw = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# Window around the first keyword hit, in chars. Tuned so the capped excerpt
# plus the schema/prompt stays well under ~3k tokens per Claude call.
_SECTION_WINDOW_BEFORE = 600
_SECTION_WINDOW_AFTER = 11_400  # ~12k total incl. the "before" window

# Segment tables often sit deep inside MD&A; widen the window so we catch
# the full per-brand / per-cohort breakout, not just the anchor sentence.
_SEGMENT_WINDOW_BEFORE = 2_000
_SEGMENT_WINDOW_AFTER = 18_000


def locate_sections(html: str) -> dict[str, str]:
    """Find the named sections in a filing; return {section: excerpt}.

    Sections that never match any keyword are omitted entirely.
    """
    text = _strip_html(html)
    sections: dict[str, str] = {}
    cap = settings.NARRATIVE_EXCERPT_CHAR_LIMIT

    for section_name, patterns in settings.NARRATIVE_SECTION_PATTERNS.items():
        combined = "|".join(f"(?:{p})" for p in patterns)
        m = re.search(combined, text, flags=re.I)
        if not m:
            continue
        if section_name == "portfolio_segments":
            before, after = _SEGMENT_WINDOW_BEFORE, _SEGMENT_WINDOW_AFTER
            section_cap = cap * 2
        else:
            before, after = _SECTION_WINDOW_BEFORE, _SECTION_WINDOW_AFTER
            section_cap = cap
        start = max(0, m.start() - before)
        end = min(len(text), m.start() + after)
        excerpt = text[start:end].strip()
        if len(excerpt) > section_cap:
            excerpt = excerpt[:section_cap]
        sections[section_name] = excerpt

    return sections


# ---------------------------------------------------------------------------
# Field routing per section — only the metrics Claude could reasonably find
# in that section are listed, so we don't pay for irrelevant nulls.
# ---------------------------------------------------------------------------


SECTION_FIELDS: dict[str, list[str]] = {
    "delinquency": [
        "delinquent_30_59_days_pct",
        "delinquent_60_89_days_pct",
        "delinquent_90_plus_days_pct",
        "delinquent_total_pct",
        "default_rate_annualized_pct",
        "contract_rescission_rate_pct",
    ],
    "fico": [
        "weighted_avg_fico_origination",
        "fico_700_plus_pct",
        "fico_below_600_pct",
        "avg_loan_size_dollars",
        "avg_contract_term_months",
        "weighted_avg_ltv_pct",
    ],
    "vintage": [
        "vintage_pools",
    ],
    "management_commentary": [
        "management_flagged_credit_concerns",
        "management_credit_commentary",
        "new_securitization_volume_mm",
        "new_securitization_advance_rate_pct",
        "weighted_avg_coupon_new_deals_pct",
        "overcollateralization_pct",
        "warehouse_facility_balance_mm",
        "retained_interests_mm",
        "gain_on_sale_margin_pct",
        "sales_to_existing_owners_pct",
        "tour_flow_count",
        "vpg_dollars",
    ],
    "portfolio_segments": [
        "segments",
    ],
}


# Canonical segment_keys accepted per ticker. Claude is instructed to use
# only these and to fall back to `consolidated` if no breakdown is disclosed.
CANONICAL_SEGMENT_KEYS: dict[str, list[str]] = {
    "HGV": ["consolidated", "legacy_hgv", "diamond", "bluegreen", "originated", "acquired_at_fv"],
    "VAC": ["consolidated", "marriott", "vistana", "welk"],
    "TNL": ["consolidated", "club_wyndham", "margaritaville"],
}


SYSTEM_PROMPT = (
    "You are a senior credit analyst extracting timeshare-receivable credit "
    "metrics from SEC filing excerpts. Return ONLY valid JSON matching the "
    "requested schema. Use null for any field the excerpt does not explicitly "
    "disclose. Never invent numbers. Express percentages as decimals (12.5% -> "
    "0.125). Dollar fields ending in _mm are in millions; fields ending in "
    "_dollars are raw USD. If a value is implied but not stated, prefer null."
)


def _strip_json_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _build_prompt(
    ticker: str,
    filing_type: str,
    period_end: str,
    section_name: str,
    fields: list[str],
    excerpt: str,
) -> str:
    if section_name == "portfolio_segments":
        return _build_segments_prompt(ticker, filing_type, period_end, excerpt)
    schema_lines = "\n".join(f'  "{k}": {METRIC_SCHEMA.get(k, "")}' for k in fields)
    return (
        f"Issuer: {ticker}. Filing type: {filing_type}. Period ended: {period_end}.\n"
        f"Section being analyzed: {section_name}.\n\n"
        f"Extract ONLY the following JSON keys from the excerpt below. Schema:\n"
        f"{{\n{schema_lines}\n}}\n\n"
        f"Rules:\n"
        f"- Return a single JSON object with exactly these keys, no others.\n"
        f"- No markdown fences, no commentary, no trailing text.\n"
        f"- Any field not disclosed in this excerpt: null.\n"
        f"- Percentages as decimals (7.1% -> 0.071).\n"
        f"- Dollar fields ending in _mm are in millions.\n"
        f"- vintage_pools: include every vintage year disclosed; "
        f"each entry {{vintage_year:int, original_balance_mm:float, "
        f"cumulative_default_rate_pct:float 0-1, as_of_period:str}}.\n\n"
        f"Excerpt:\n-----\n{excerpt}\n-----"
    )


def _build_segments_prompt(
    ticker: str,
    filing_type: str,
    period_end: str,
    excerpt: str,
) -> str:
    """Segment extraction prompt.

    Claude returns {"segments": [...]} with one entry per disclosed segment
    (brand or acquisition cohort) plus a `consolidated` entry when a
    consolidated total is reported.
    """
    allowed = CANONICAL_SEGMENT_KEYS.get(ticker.upper(), ["consolidated"])
    allowed_list = ", ".join(f'"{k}"' for k in allowed)
    return (
        f"Issuer: {ticker}. Filing type: {filing_type}. Period ended: {period_end}.\n"
        f"Section being analyzed: portfolio_segments.\n\n"
        f"Extract one entry per disclosed receivables segment. Return:\n"
        f"{{\n"
        f'  "segments": [\n'
        f"    {{\n"
        f'      "segment_key": str,          // one of: {allowed_list}\n'
        f'      "segment_label": str,        // human label, e.g. "Legacy-HGV"\n'
        f'      "segment_type": str,         // "consolidated" | "brand" | "acquisition_cohort"\n'
        f'      "gross_receivables_total_mm": float|null,\n'
        f'      "allowance_for_loan_losses_mm": float|null,\n'
        f'      "allowance_coverage_pct": float|null,\n'
        f'      "provision_for_loan_losses_mm": float|null,\n'
        f'      "delinquent_30_59_days_pct": float|null,\n'
        f'      "delinquent_60_89_days_pct": float|null,\n'
        f'      "delinquent_90_plus_days_pct": float|null,\n'
        f'      "delinquent_total_pct": float|null,\n'
        f'      "default_rate_annualized_pct": float|null,\n'
        f'      "weighted_avg_fico_origination": int|null,\n'
        f'      "fico_700_plus_pct": float|null,\n'
        f'      "fico_below_600_pct": float|null,\n'
        f'      "originations_mm": float|null,\n'
        f'      "as_of_period": str          // ISO date, usually = period_end\n'
        f"    }}\n"
        f"  ]\n"
        f"}}\n\n"
        f"Rules:\n"
        f"- Return a single JSON object with exactly the key `segments`.\n"
        f"- No markdown fences, no commentary.\n"
        f"- Use ONLY segment_key values from the allowed list above. Do not invent keys.\n"
        f"- If the filing discloses a consolidated total, include a `consolidated` entry.\n"
        f"- If the filing discloses brand-level breakouts (e.g. Legacy-HGV, Diamond, Bluegreen, "
        f"Marriott Vacation Club, Vistana, Welk, Club Wyndham, Margaritaville), add one entry "
        f"per brand with segment_type=\"brand\".\n"
        f"- If the filing discloses originated vs acquired-at-fair-value cohorts, add entries "
        f"with segment_type=\"acquisition_cohort\" and segment_key `originated` or "
        f"`acquired_at_fv`.\n"
        f"- Do NOT invent segments. If only a consolidated total is reported, return a single "
        f"`consolidated` entry.\n"
        f"- Any field within a segment not disclosed in this excerpt: null.\n"
        f"- Percentages as decimals (7.1% -> 0.071). Dollar _mm fields in millions.\n\n"
        f"Excerpt:\n-----\n{excerpt}\n-----"
    )


def _call_claude(
    client,
    ticker: str,
    filing_type: str,
    period_end: str,
    section_name: str,
    fields: list[str],
    excerpt: str,
) -> tuple[dict, dict]:
    """One Claude call for one section. Returns (parsed_json_or_nulls, usage)."""
    prompt = _build_prompt(ticker, filing_type, period_end, section_name, fields, excerpt)
    try:
        resp = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        log.error("claude call failed for %s/%s: %s", ticker, section_name, e)
        return ({k: None for k in fields}, {"input_tokens": 0, "output_tokens": 0, "error": str(e)})

    raw = resp.content[0].text if resp.content else ""
    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0) if hasattr(resp, "usage") else 0,
        "output_tokens": getattr(resp.usage, "output_tokens", 0) if hasattr(resp, "usage") else 0,
    }
    cleaned = _strip_json_fences(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("PARSE_ERROR section=%s %s %s %s; nulling fields",
                    section_name, ticker, filing_type, period_end)
        if section_name == "portfolio_segments":
            return ({"segments": []}, usage)
        return ({k: None for k in fields}, usage)

    if section_name == "portfolio_segments":
        segs = parsed.get("segments")
        if not isinstance(segs, list):
            segs = []
        # Defensive filter: drop entries with non-string segment_key.
        segs = [s for s in segs if isinstance(s, dict) and isinstance(s.get("segment_key"), str)]
        return ({"segments": segs}, usage)

    # Keep only requested keys; null the rest.
    out = {k: parsed.get(k, None) for k in fields}
    return out, usage


def extract_from_sections(
    client,
    ticker: str,
    filing_type: str,
    period_end: str,
    sections: dict[str, str],
) -> tuple[dict, dict]:
    """Run one Claude call per located section; return (merged_fields, usage_summary)."""
    merged: dict = {}
    calls: list[dict] = []
    total_in = 0
    total_out = 0

    for section_name, excerpt in sections.items():
        fields = SECTION_FIELDS.get(section_name, [])
        if not fields:
            continue
        log.info("claude narrative: %s %s %s section=%s (%d chars)",
                 ticker, filing_type, period_end, section_name, len(excerpt))
        result, usage = _call_claude(
            client, ticker, filing_type, period_end,
            section_name, fields, excerpt,
        )
        for k, v in result.items():
            # segments is section-scoped to portfolio_segments; never let
            # another section overwrite it.
            if k == "segments" and section_name != "portfolio_segments":
                continue
            # First non-null wins (stable across sections; matches v1 merge).
            if merged.get(k) in (None, [], "") and v not in (None, [], ""):
                merged[k] = v
        calls.append({
            "section": section_name,
            "excerpt_chars": len(excerpt),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        })
        total_in += usage.get("input_tokens", 0) or 0
        total_out += usage.get("output_tokens", 0) or 0

    return merged, {
        "calls": calls,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
    }
