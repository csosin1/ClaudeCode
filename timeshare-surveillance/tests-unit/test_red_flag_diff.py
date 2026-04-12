"""Unit tests for red_flag_diff.

Run from the project root:
    venv/bin/python -m pytest tests-unit/ -q
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def fresh_modules(tmp_path, monkeypatch):
    """Redirect settings paths into a tmp dir and re-import target modules."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "raw").mkdir()

    # Fresh import of settings so we can monkeypatch paths.
    if "config.settings" in sys.modules:
        del sys.modules["config.settings"]
    if "pipeline.red_flag_diff" in sys.modules:
        del sys.modules["pipeline.red_flag_diff"]

    import config.settings as settings  # noqa: WPS433

    monkeypatch.setattr(settings, "DATA_DIR", data_dir, raising=False)
    monkeypatch.setattr(settings, "RAW_DIR", data_dir / "raw", raising=False)
    monkeypatch.setattr(settings, "COMBINED_JSON", data_dir / "combined.json", raising=False)
    monkeypatch.setattr(settings, "FLAG_STATE_JSON", data_dir / "flag_state.json", raising=False)

    import pipeline.red_flag_diff as rfd  # noqa: WPS433

    importlib.reload(rfd)
    monkeypatch.setattr(rfd, "settings", settings, raising=False)
    return settings, rfd


def _combined_with(metric_overrides_per_ticker: dict[str, dict]) -> list[dict]:
    """Build a minimal combined.json with one record per ticker."""
    out = []
    for ticker, overrides in metric_overrides_per_ticker.items():
        rec = {
            "ticker": ticker,
            "period_end": "2025-03-31",
            "filing_type": "10-Q",
            "accession": f"{ticker}-ACC",
        }
        rec.update(overrides)
        out.append(rec)
    return out


def test_evaluate_triggers_critical_on_high_delinquency(fresh_modules):
    _, rfd = fresh_modules
    rec = {"delinquent_90_plus_days_pct": 0.08, "allowance_coverage_pct": 0.12}
    flags = rfd.evaluate(rec)
    assert "delinquent_90_plus_days_pct" in flags
    assert flags["delinquent_90_plus_days_pct"]["severity"] == "CRITICAL"


def test_evaluate_falls_through_to_warning(fresh_modules):
    _, rfd = fresh_modules
    rec = {"delinquent_90_plus_days_pct": 0.06}
    flags = rfd.evaluate(rec)
    assert flags["delinquent_90_plus_days_pct"]["severity"] == "WARNING"


def test_no_flag_when_under_threshold(fresh_modules):
    _, rfd = fresh_modules
    rec = {"delinquent_90_plus_days_pct": 0.03, "allowance_coverage_pct": 0.15}
    flags = rfd.evaluate(rec)
    assert flags == {}


def test_run_emits_new_flag_and_sets_state(fresh_modules):
    settings, rfd = fresh_modules
    combined = _combined_with({
        "HGV": {"delinquent_90_plus_days_pct": 0.08},
        "VAC": {"delinquent_90_plus_days_pct": 0.03, "allowance_coverage_pct": 0.15},
    })
    settings.COMBINED_JSON.write_text(json.dumps(combined))

    summary, changed = rfd.run()
    assert changed is True
    assert len(summary["new"]) >= 1
    metrics_new = {(f["ticker"], f["metric"]) for f in summary["new"]}
    assert ("HGV", "delinquent_90_plus_days_pct") in metrics_new

    # state written
    state = json.loads(settings.FLAG_STATE_JSON.read_text())
    assert state["HGV"]["delinquent_90_plus_days_pct"]["severity"] == "CRITICAL"


def test_run_detects_escalated_and_resolved(fresh_modules):
    settings, rfd = fresh_modules
    # Pre-seed prior state: HGV was WARNING on delinquent, VAC had a WARNING on coverage
    prior = {
        "HGV": {
            "delinquent_90_plus_days_pct": {
                "severity": "WARNING", "value": 0.06, "threshold": 0.05, "op": ">=",
            },
        },
        "VAC": {
            "allowance_coverage_pct": {
                "severity": "WARNING", "value": 0.09, "threshold": 0.10, "op": "<",
            },
        },
    }
    settings.FLAG_STATE_JSON.write_text(json.dumps(prior))

    # New data: HGV delinquency worsens to CRITICAL; VAC coverage recovers.
    combined = _combined_with({
        "HGV": {"delinquent_90_plus_days_pct": 0.08},
        "VAC": {"allowance_coverage_pct": 0.15, "delinquent_90_plus_days_pct": 0.02},
    })
    settings.COMBINED_JSON.write_text(json.dumps(combined))

    summary, changed = rfd.run()
    assert changed is True
    assert any(e["ticker"] == "HGV" and e["metric"] == "delinquent_90_plus_days_pct"
               for e in summary["escalated"])
    assert any(r["ticker"] == "VAC" and r["metric"] == "allowance_coverage_pct"
               for r in summary["resolved"])


def test_force_email_flag_always_marks_changes(fresh_modules):
    settings, rfd = fresh_modules
    combined = _combined_with({"HGV": {"delinquent_90_plus_days_pct": 0.02}})
    settings.COMBINED_JSON.write_text(json.dumps(combined))
    # Prior state empty → no diff, but --force-email should still flag changed=True
    summary, changed = rfd.run(force_email=True)
    assert changed is True
    assert summary.get("weekly") is True
