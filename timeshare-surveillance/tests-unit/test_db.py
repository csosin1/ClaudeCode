"""Unit tests for pipeline.db — uses a tmp sqlite path, no network."""

from __future__ import annotations

from pathlib import Path

from pipeline import db as pdb
from pipeline.metric_schema import METRIC_SCHEMA, null_record


def _sample_record() -> dict:
    rec = null_record()
    rec.update({
        "ticker": "HGV",
        "filing_type": "10-Q",
        "period_end": "2025-03-31",
        "accession": "0001674168-25-000012",
        "filed_date": "2025-05-02",
        "source_url": "fixture://hgv",
        "extracted_at": "2026-04-13T00:00:00+00:00",
        "gross_receivables_total_mm": 3450.0,
        "allowance_for_loan_losses_mm": 380.0,
        "allowance_coverage_pct": 0.110,
        "delinquent_90_plus_days_pct": 0.062,
        "management_flagged_credit_concerns": False,
        "vintage_pools": [
            {"vintage_year": 2023, "original_balance_mm": 1050.0,
             "cumulative_default_rate_pct": 0.054, "as_of_period": "2025-03-31"},
        ],
    })
    return rec


def test_init_db_creates_filings_table(tmp_path: Path):
    db_path = tmp_path / "surveillance.db"
    pdb.init_db(db_path)
    assert db_path.exists()
    with pdb.connect(db_path) as conn:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
    assert "filings" in tables


def test_upsert_and_export_round_trip_preserves_metric_schema_keys(tmp_path: Path):
    db_path = tmp_path / "surveillance.db"
    pdb.init_db(db_path)
    rec = _sample_record()
    pdb.upsert_filing(db_path, rec)

    out = pdb.export_combined(db_path)
    assert len(out) == 1
    got = out[0]

    # Bookkeeping fields preserved.
    for k in ("ticker", "filing_type", "period_end", "accession",
              "filed_date", "source_url", "extracted_at"):
        assert got.get(k) == rec[k], f"mismatch on {k}"

    # Every METRIC_SCHEMA key is present in the exported record.
    for k in METRIC_SCHEMA.keys():
        assert k in got, f"missing METRIC_SCHEMA key in export: {k}"

    # Values we wrote are intact.
    assert got["gross_receivables_total_mm"] == 3450.0
    assert got["allowance_for_loan_losses_mm"] == 380.0
    assert got["allowance_coverage_pct"] == 0.110
    assert got["delinquent_90_plus_days_pct"] == 0.062
    assert got["management_flagged_credit_concerns"] is False
    assert got["vintage_pools"] == rec["vintage_pools"]


def test_upsert_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "surveillance.db"
    pdb.init_db(db_path)
    rec = _sample_record()
    pdb.upsert_filing(db_path, rec)

    # Second upsert with changed values overwrites, does NOT duplicate.
    rec["gross_receivables_total_mm"] = 3500.0
    pdb.upsert_filing(db_path, rec)

    out = pdb.export_combined(db_path)
    assert len(out) == 1
    assert out[0]["gross_receivables_total_mm"] == 3500.0


def test_export_empty_when_db_missing(tmp_path: Path):
    db_path = tmp_path / "does_not_exist.db"
    assert pdb.export_combined(db_path) == []
