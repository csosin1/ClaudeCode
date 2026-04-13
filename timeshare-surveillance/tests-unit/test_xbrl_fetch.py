"""Unit tests for xbrl_fetch — fixture-only, no network."""

from __future__ import annotations

from pathlib import Path

from pipeline import xbrl_fetch as xf

FIXTURE = Path(__file__).resolve().parent.parent / "pipeline" / "fixtures" / "hgv_companyfacts_sample.json"


def test_fixture_exists():
    assert FIXTURE.exists(), f"missing fixture: {FIXTURE}"


def test_extract_metrics_by_period_maps_three_metrics_over_two_periods():
    cf = xf.load_companyfacts(cik="0001674168", fixture_path=FIXTURE)
    by_period = xf.extract_metrics_by_period(cf)

    # Two periods disclosed in the fixture.
    assert set(by_period.keys()) == {"2024-12-31", "2025-03-31"}

    q1 = by_period["2025-03-31"]
    fy = by_period["2024-12-31"]

    # Balance-sheet tags (USD -> millions).
    assert q1["gross_receivables_total_mm"] == 3450.0
    assert q1["allowance_for_loan_losses_mm"] == 380.0
    assert fy["gross_receivables_total_mm"] == 3380.0
    assert fy["allowance_for_loan_losses_mm"] == 372.0

    # Flow tag (provision).
    assert q1["provision_for_loan_losses_mm"] == 54.0
    assert fy["provision_for_loan_losses_mm"] == 210.0

    # Company-extension originations (namespace "hgv" in the fixture).
    assert q1["originations_mm"] == 375.0
    assert fy["originations_mm"] == 1450.0

    # Derived coverage.
    assert q1["allowance_coverage_pct"] == round(380.0 / 3450.0, 6)


def test_fetch_metrics_top_level_helper_round_trips():
    by_period = xf.fetch_metrics(cik="0001674168", fixture_path=FIXTURE)
    assert "2025-03-31" in by_period
    # Spot check at least three metrics present on one period.
    q1 = by_period["2025-03-31"]
    present = [k for k in (
        "gross_receivables_total_mm",
        "allowance_for_loan_losses_mm",
        "provision_for_loan_losses_mm",
        "originations_mm",
    ) if q1.get(k) is not None]
    assert len(present) >= 3
