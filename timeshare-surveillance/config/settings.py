"""Timeshare surveillance configuration.

All env-backed secrets are read via os.environ.get so that importing this
module never crashes when a key is missing. Call sites that require a secret
should surface a clear error there.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
COMBINED_JSON = DATA_DIR / "combined.json"
FLAG_STATE_JSON = DATA_DIR / "flag_state.json"
SEEN_ACCESSIONS_JSON = DATA_DIR / "seen_accessions.json"
FIXTURES_DIR = BASE_DIR / "pipeline" / "fixtures"

LOG_DIR = Path("/var/log/timeshare-surveillance")
LOG_FILE = LOG_DIR / "pipeline.log"

# If set by the deploy script, merge.py mirrors combined.json here so nginx
# can serve it alongside the dashboard at ./data/combined.json.
NGINX_SERVE_DIR = os.environ.get("DASHBOARD_SERVE_DIR")

# ----- EDGAR -----

# Public timeshare issuers we monitor. CIKs are zero-padded to 10 digits for
# the data.sec.gov submissions API.
TARGETS = [
    {
        "ticker": "HGV",
        "name": "Hilton Grand Vacations Inc.",
        "cik": "0001674168",
    },
    {
        "ticker": "VAC",
        "name": "Marriott Vacations Worldwide Corporation",
        "cik": "0001524358",
    },
    {
        "ticker": "TNL",
        "name": "Travel + Leisure Co.",
        "cik": "0001361658",
    },
]

EDGAR_USER_AGENT = "CAS Investment Partners research@casinvestmentpartners.com"
EDGAR_RATE_LIMIT_PER_SEC = 8
FILING_TYPES = ["10-K", "10-Q"]
LOOKBACK_FILINGS = 12

# ----- Anthropic -----

ANTHROPIC_MODEL = "claude-opus-4-5"
# chars/4 heuristic; keep chunks under this to stay within context safely.
CHUNK_CHAR_LIMIT = 75_000 * 4          # ~75k tokens
CHUNK_OVERLAP_CHARS = 5_000 * 4        # ~5k tokens overlap
FULL_DOC_CHAR_LIMIT = 80_000 * 4       # above this we chunk

# ----- Thresholds (CRITICAL + WARNING) — exactly per user spec.
# comparator tuples: (op, value). op is ">" (strict), "<" (strict), "==".
# Keep these in sync with the dashboard THRESHOLDS constant.
THRESHOLDS = {
    "CRITICAL": {
        "delinquent_90_plus_days_pct":          (">",  0.07),
        "delinquent_total_pct":                 (">",  0.15),
        "allowance_coverage_pct":               ("<",  0.10),
        "allowance_coverage_pct_qoq_delta":     (">",  0.02),   # 200bps deterioration
        "gain_on_sale_margin_pct":              ("<",  0.05),
        "new_securitization_advance_rate_qoq":  ("<", -0.03),   # -300bps
        "management_flagged_credit_concerns":   ("==", True),
    },
    "WARNING": {
        "delinquent_90_plus_days_pct":          (">",  0.05),
        "delinquent_total_pct":                 (">",  0.10),
        "allowance_coverage_pct":               ("<",  0.12),
        "fico_below_600_pct":                   (">",  0.15),
        "weighted_avg_fico_origination":        ("<",  680),
        "originations_mm_yoy_change_pct":       ("<", -0.15),
        "contract_rescission_rate_pct":         (">",  0.15),
        "provision_yoy_change_pct":             (">",  0.25),
    },
}

# ----- Secrets (filled from .env via systemd EnvironmentFile) -----
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_PORT = int(os.environ.get("ADMIN_PORT", "8510"))

# Public dashboard URL (used in email alert footer).
DASHBOARD_URL = os.environ.get(
    "DASHBOARD_URL", "https://casinv.dev/timeshare-surveillance/"
)


def missing_secrets() -> list[str]:
    """Return the list of env vars that users still need to populate."""
    missing = []
    for key in ("ANTHROPIC_API_KEY", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ALERT_EMAIL"):
        if not os.environ.get(key):
            missing.append(key)
    return missing


def require(env_var: str) -> str:
    """Fetch an env var or raise a helpful error at the call site."""
    val = os.environ.get(env_var, "")
    if not val:
        raise RuntimeError(
            f"Environment variable {env_var} is not set. "
            f"Populate it via the admin setup page or .env file."
        )
    return val
