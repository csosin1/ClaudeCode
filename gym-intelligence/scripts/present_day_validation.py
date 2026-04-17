#!/usr/bin/env python3
"""
Present-day OHSOME coverage validation.

For each of 19 chains:
  1. Fetch the live locator page (httpx, browser UA, 30s timeout).
  2. Strip HTML tags, truncate to 30k chars, ask claude-haiku-4-5 for the count.
  3. Pull OHSOME's 2026-03-31 total for the same chain from gyms.db (sum countries).
  4. Compute coverage_pct and deltas.

Runs on prod. Writes to /opt/gym-intelligence-preview/writeup/data/present-day-coverage-validation.json.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from anthropic import Anthropic
from anthropic import APIStatusError, APIConnectionError, APITimeoutError

# ---------- Config ----------
DB_PATH = "/opt/gym-intelligence-preview/gyms.db"
OUT_PATH = "/opt/gym-intelligence-preview/writeup/data/present-day-coverage-validation.json"
SNAPSHOT_DATE = "2026-03-31"
TODAY = "2026-04-17"
HAIKU_MODEL = "claude-haiku-4-5-20251001"

LOCATORS = {
    "Basic-Fit":        "https://www.basic-fit.com/en/clubs",
    "clever fit":       "https://www.clever-fit.com/fitnessstudio-finden",
    "Fitness Park":     "https://www.fitnesspark.fr/clubs",
    "L'Orange Bleue":   "https://www.lorangebleue.fr/nos-clubs",
    "McFit":            "https://www.mcfit.com/de/studios",
    "KeepCool":         "https://www.keepcool.fr/salle-de-sport",
    "SportCity":        "https://www.sportcity.nl/clubs",
    "Anytime Fitness":  "https://www.anytimefitness.com/gyms/",
    "FitX":             "https://www.fitx.de/studios",
    "EasyFitness":      "https://easyfitness.club/studios",
    "Snap Fitness":     "https://www.snapfitness.com/gb/gyms/",
    "Activ Fitness":    "https://www.activfitness.ch/de/club-finder",
    "PureGym":          "https://www.puregym.com/gyms/",
    "Magic Form":       "https://www.magicform.fr/nos-clubs",
    "L'Appart Fitness": "https://www.lappartfitness.com/nos-salles",
    "Neoness":          "https://neoness.fr/nos-clubs",
    "Liberty Gym":      "https://www.libertygym.fr/nos-clubs",
    "TrainMore":        "https://trainmore.nl/clubs",
    "update Fitness":   "https://www.update-fitness.ch/fitnesscenter",
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.3 Safari/605.1.15"
)

HAIKU_PROMPT_TEMPLATE = """You are counting gym/club locations on a chain's store-locator page. The chain is: {name}.
Below is the stripped text content of their current "find a club" / "nos clubs" / "studios" page.

If the page shows a stated total ("Nos 400 clubs"), prefer that number.
Otherwise count the distinct venue/city entries in the list.
If the page is broken, empty, a cookie wall, a single-club detail page, or clearly unrelated to a club list, return null.

Return ONLY JSON: {{"count": <integer or null>, "basis": "stated_number"|"counted_list"|"unreachable", "reason": "<one line>", "confidence": "high"|"medium"|"low"}}

Page content:
{text}
"""

# ---------- Helpers ----------

def load_env():
    """Load ANTHROPIC_API_KEY from /opt/gym-intelligence-preview/.env if not already set."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    envfile = Path("/opt/gym-intelligence-preview/.env")
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k.strip(), v)


def strip_html(html: str) -> str:
    # Remove script/style blocks entirely
    html = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style\b[^>]*>.*?</style>", " ", html, flags=re.S | re.I)
    # Replace tags with space
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_page(url: str) -> tuple[str | None, str | None]:
    """Return (text, error). Retry twice on timeout."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en,fr-FR;q=0.8,fr;q=0.7,de;q=0.6,nl;q=0.5",
    }
    for attempt in range(2):
        try:
            with httpx.Client(follow_redirects=True, timeout=30.0, headers=headers) as client:
                r = client.get(url)
            if r.status_code >= 400:
                return None, f"HTTP {r.status_code}"
            return r.text, None
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            if attempt == 0:
                time.sleep(8)
                continue
            return None, f"fetch error: {type(e).__name__}: {e}"
        except Exception as e:
            return None, f"fetch error: {type(e).__name__}: {e}"
    return None, "fetch exhausted"


def ask_haiku(client: Anthropic, name: str, text: str) -> dict:
    """Call Haiku with backoff on 5xx."""
    prompt = HAIKU_PROMPT_TEMPLATE.format(name=name, text=text[:30000])
    delays = [4, 16, 64]
    last_err = None
    for i, delay in enumerate([0] + delays):
        if delay:
            time.sleep(delay)
        try:
            resp = client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            content = resp.content[0].text.strip()
            # Strip code fences if present
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S).strip()
            # Try to locate the JSON object
            m = re.search(r"\{.*\}", content, flags=re.S)
            if m:
                content = m.group(0)
            data = json.loads(content)
            return {
                "count": data.get("count"),
                "basis": data.get("basis", "unknown"),
                "reason": data.get("reason", ""),
                "confidence": data.get("confidence", "low"),
            }
        except (APIStatusError, APIConnectionError, APITimeoutError) as e:
            last_err = e
            status = getattr(e, "status_code", None)
            if status and status not in (500, 502, 503, 504, 529):
                break
            if i >= len(delays):
                break
            continue
        except Exception as e:
            last_err = e
            break
    return {
        "count": None,
        "basis": "unreachable",
        "reason": f"haiku call failed: {last_err}",
        "confidence": "low",
    }


def ohsome_total(conn: sqlite3.Connection, chain_name: str) -> int | None:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(s.location_count), 0)
        FROM snapshots s
        JOIN chains c ON c.id = s.chain_id
        WHERE c.canonical_name = ? AND s.snapshot_date = ?
        """,
        (chain_name, SNAPSHOT_DATE),
    ).fetchone()
    if row is None:
        return None
    return int(row[0] or 0)


# ---------- Main ----------

def main():
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = Anthropic()
    conn = sqlite3.connect(DB_PATH)

    cells = []
    unreachable = 0

    for name, url in LOCATORS.items():
        print(f"[{name}] fetching {url}", flush=True)
        ohsome = ohsome_total(conn, name)
        html, err = fetch_page(url)
        if html is None:
            print(f"  unreachable: {err}", flush=True)
            cells.append({
                "chain": name,
                "locator_url": url,
                "live_count": None,
                "live_basis": "unreachable",
                "live_confidence": "low",
                "live_reason": err,
                "ohsome_2026q1": ohsome,
                "delta": None,
                "delta_pct": None,
                "ohsome_coverage_pct": None,
            })
            unreachable += 1
            time.sleep(2)
            continue

        text = strip_html(html)
        result = ask_haiku(client, name, text)
        live = result["count"]

        # Sanity gate: abs(delta_pct) > 500 → skip chain
        delta = None
        delta_pct = None
        coverage = None
        skipped = False
        if live is not None and ohsome is not None and live > 0:
            delta = ohsome - live
            delta_pct = round(100.0 * delta / live, 2)
            if abs(delta_pct) > 500:
                print(f"  SANITY: delta_pct={delta_pct} — skipping chain", flush=True)
                skipped = True
                live_out = None
                basis_out = "unreachable"
                reason_out = f"sanity skip; live={live} vs ohsome={ohsome} gave delta_pct={delta_pct}"
                confidence_out = "low"
                delta = None
                delta_pct = None
                coverage = None
                unreachable += 1
            else:
                coverage = round(100.0 * ohsome / live, 2)

        if not skipped:
            live_out = live
            basis_out = result["basis"]
            reason_out = result["reason"]
            confidence_out = result["confidence"]
            if live is None:
                unreachable += 1

        cell = {
            "chain": name,
            "locator_url": url,
            "live_count": live_out,
            "live_basis": basis_out,
            "live_confidence": confidence_out,
            "live_reason": reason_out,
            "ohsome_2026q1": ohsome,
            "delta": delta,
            "delta_pct": delta_pct,
            "ohsome_coverage_pct": coverage,
        }
        cells.append(cell)
        print(f"  live={live_out} ohsome={ohsome} coverage={coverage}", flush=True)
        time.sleep(2)

    conn.close()

    # Metrics
    coverages = [c["ohsome_coverage_pct"] for c in cells if c["ohsome_coverage_pct"] is not None]
    live_counts = [c for c in cells if c["live_count"] is not None]
    cells_with_live = len(live_counts)
    cells_unreachable = len(cells) - cells_with_live

    if coverages:
        median_cov = round(statistics.median(coverages), 2)
        sorted_c = sorted(coverages)
        def pct(p):
            if not sorted_c:
                return None
            k = (len(sorted_c) - 1) * (p / 100.0)
            f = int(k)
            c = min(f + 1, len(sorted_c) - 1)
            if f == c:
                return round(sorted_c[f], 2)
            return round(sorted_c[f] + (sorted_c[c] - sorted_c[f]) * (k - f), 2)
        p10 = pct(10)
        p90 = pct(90)
        chains_within_90 = sum(1 for v in coverages if v >= 90)
        chains_below_60 = sum(1 for v in coverages if v < 60)
    else:
        median_cov = p10 = p90 = None
        chains_within_90 = chains_below_60 = 0

    # Recommendation
    if median_cov is None:
        recommendation = "RED"
    elif median_cov > 85 and chains_below_60 == 0:
        recommendation = "GREEN"
    elif 70 <= median_cov <= 85:
        recommendation = "YELLOW"
    elif median_cov < 70:
        recommendation = "RED"
    else:
        # median > 85 but some chains below 60 → YELLOW
        recommendation = "YELLOW"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    out = {
        "generated": now,
        "comparison_basis": (
            "OHSOME snapshot 2026-03-31 vs live chain-locator scrape 2026-04-17 "
            "(17-day gap; real-world club changes in that window expected <2pct for most chains)"
        ),
        "cells": cells,
        "metrics": {
            "cells_with_live_count": cells_with_live,
            "cells_unreachable": cells_unreachable,
            "median_ohsome_coverage_pct": median_cov,
            "p10_coverage_pct": p10,
            "p90_coverage_pct": p90,
            "chains_within_90pct": chains_within_90,
            "chains_below_60pct": chains_below_60,
        },
        "recommendation": recommendation,
    }

    out_path = Path(OUT_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nWrote {OUT_PATH}", flush=True)
    print(f"median_coverage={median_cov}  recommendation={recommendation}", flush=True)


if __name__ == "__main__":
    main()
