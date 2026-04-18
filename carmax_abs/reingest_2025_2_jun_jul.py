#!/usr/bin/env python3
"""Re-ingest CarMax 2025-2 May/June/July 2025 10-D filings (audit finding #8).

PROBLEM
-------
pool_performance had a 92-day coverage gap for deal 2025-2 between 5/15/2025
and 8/15/2025 — no rows for the June or July 2025 distribution periods, even
though the underlying 10-D filings existed on EDGAR and were flagged
`ingested_pool=1` in the `filings` table.

ROOT CAUSE
----------
The May, June, and July 2025 CarMax servicer certificates (accessions
0002063979-25-000005 / -000010 / -000015) were all filed with a stale
"Distribution Date 5/15/2025" header on the cover table, despite the
underlying pool data progressing correctly (balances declining, losses rising)
between filings. This is an **issuer-side data-quality error** in the HTML
cover page, not a parser defect.

Because the parser (correctly) reads the header literally, all three filings
produced the same `distribution_date='5/15/2025'` and collided on the
pool_performance primary key `(deal, distribution_date)`. Whichever was
ingested last won; the other two rows were silently overwritten, leaving the
gap.

FIX
---
Call the parser as usual, but override `distribution_date` using the 10-D
filing_date (which IS correct on EDGAR's filing index) before inserting.
This does NOT modify the parser — only the one-off ingest path for these
three filings, which are the only certs observed to suffer this issuer bug.

Idempotent: safe to re-run. Uses INSERT OR REPLACE keyed on
(deal, distribution_date).
"""
import os
import sys
import sqlite3
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from carmax_abs.ingestion.servicer_parser import parse_servicer_certificate
from carmax_abs.ingestion.edgar_client import download_document
from carmax_abs.config import DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# (accession, servicer_cert_url, correct_distribution_date)
# Correct distribution dates are the 10-D filing_date values from EDGAR.
TARGETS = [
    ("0002063979-25-000005",
     "https://www.sec.gov/Archives/edgar/data/2063979/000206397925000005/a2025-2ex991051525.htm",
     "5/15/2025"),
    ("0002063979-25-000010",
     "https://www.sec.gov/Archives/edgar/data/2063979/000206397925000010/a2025-2ex991061625.htm",
     "6/16/2025"),
    ("0002063979-25-000015",
     "https://www.sec.gov/Archives/edgar/data/2063979/000206397925000015/a2025-2ex991071525.htm",
     "7/15/2025"),
]


def main(db_path: str = DB_PATH) -> None:
    # Clear any rows that may have been written under incorrect dates
    conn = sqlite3.connect(db_path)
    conn.execute(
        "DELETE FROM pool_performance "
        "WHERE deal='2025-2' "
        "AND distribution_date IN ('5/15/2025','6/15/2025','6/16/2025','7/15/2025')"
    )
    conn.commit()
    conn.close()

    for acc, url, correct_date in TARGETS:
        html = download_document(url)
        if not html:
            logger.error(f"Failed to download {acc}")
            continue
        data = parse_servicer_certificate(html)
        logger.info(
            f"{acc}: parser_distribution_date={data.get('distribution_date')!r} "
            f"-> overriding to {correct_date}"
        )
        data["distribution_date"] = correct_date

        conn = sqlite3.connect(db_path)
        cols = ["deal", "distribution_date", "accession_number"]
        vals = ["2025-2", correct_date, acc]
        for k, v in data.items():
            if k == "distribution_date" or v is None:
                continue
            cols.append(k)
            vals.append(v)
        placeholders = ",".join(["?"] * len(cols))
        conn.execute(
            f"INSERT OR REPLACE INTO pool_performance ({','.join(cols)}) "
            f"VALUES ({placeholders})",
            vals,
        )
        conn.execute(
            "UPDATE filings SET ingested_pool=1 WHERE accession_number=?",
            (acc,),
        )
        conn.commit()
        conn.close()
        logger.info(
            f"  stored: cum_net_loss={data.get('cumulative_net_losses')} "
            f"ending_pool={data.get('ending_pool_balance')}"
        )


if __name__ == "__main__":
    main()
