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
SQLITE_DB_PATH = DATA_DIR / "surveillance.db"

# Persistent on-disk cache of raw SEC responses. Survives redeploys so a
# 5-year backfill never re-downloads — see pipeline/sec_cache.py.
SEC_CACHE_DIR = DATA_DIR / "sec_cache"
SEC_CACHE_XBRL_TTL_HOURS = int(os.environ.get("SEC_CACHE_XBRL_TTL_HOURS", "168"))

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
LOOKBACK_FILINGS = 45  # HGV has 38 total 10-K+10-Q since 2017 spinoff; 45 leaves headroom

# ----- Anthropic -----

ANTHROPIC_MODEL = "claude-sonnet-4-6"
# Legacy chunking constants (unused after XBRL-first refactor, kept to avoid
# breaking any out-of-tree callers).
CHUNK_CHAR_LIMIT = 75_000 * 4
CHUNK_OVERLAP_CHARS = 5_000 * 4
FULL_DOC_CHAR_LIMIT = 80_000 * 4

# Narrative excerpt budget — cap per section handed to Claude (~5k tokens).
# Wider window helps us capture real delinquency/FICO/vintage tables that
# often sit deep in MD&A after forward-looking-statements boilerplate.
NARRATIVE_EXCERPT_CHAR_LIMIT = 20_000

# ----- XBRL tag mapping -----
#
# Each METRIC_SCHEMA key maps to one or more candidate us-gaap (or company-ext)
# concept names. The fetcher walks candidates in order and stops at the first
# that has a value for the target period. `scale` multiplies the raw USD value
# so "_mm" fields end up in millions.
#
# Tag names are the un-namespaced local names as they appear in companyfacts
# JSON (SEC exposes us-gaap and any company-specific extension namespace under
# `facts.<namespace>.<TagName>`). The fetcher searches us-gaap first, then any
# other namespace present in the JSON.

XBRL_TAG_MAP: dict[str, dict] = {
    "gross_receivables_total_mm": {
        "tags": [
            "FinancingReceivableBeforeAllowanceForCreditLosses",
            "FinancingReceivableBeforeAllowanceForCreditLoss",
            "TimeshareFinancingReceivable",
            "FinancingReceivable",
            "NotesReceivableGross",
        ],
        "unit": "USD",
        "scale": 1e-6,
    },
    "allowance_for_loan_losses_mm": {
        "tags": [
            # Plural is the spelling HGV/TNL actually use in practice.
            "FinancingReceivableAllowanceForCreditLosses",
            "FinancingReceivableAllowanceForCreditLoss",
            "TimeSharingTransactionsAllowanceForUncollectibleAccounts",
            "AllowanceForLoanAndLeaseLossesReceivablesNetReportedAmount",
            "LoansAndLeasesReceivableAllowance",
            "AllowanceForLoanAndLeaseLossesProvisionForLossNet",
            "AllowanceForNotesAndLoansReceivableCurrent",
            "AllowanceForNotesAndLoansReceivableNoncurrent",
            # NB: AllowanceForDoubtfulAccountsReceivable was previously
            # listed as a fallback but it's semantically wrong for timeshare
            # lenders — it captures non-timeshare doubtful accounts
            # (~$93M for HGV 2025 vs the real ~$900M ACL). Removed. For
            # HGV post-2021 and VAC throughout, XBRL returns null here;
            # the `balance_sheet` narrative section fills the gap.
        ],
        "unit": "USD",
        "scale": 1e-6,
    },
    "net_receivables_mm": {
        "tags": [
            "FinancingReceivableAfterAllowanceForCreditLosses",
            "FinancingReceivableAfterAllowanceForCreditLoss",
            "NotesReceivableNet",
        ],
        "unit": "USD",
        "scale": 1e-6,
    },
    "provision_for_loan_losses_mm": {
        "tags": [
            "ProvisionForLoanAndLeaseLosses",
            "ProvisionForLoanLossesExpensed",
            "FinancingReceivableAllowanceForCreditLossesPeriodIncreaseDecrease",
            "ProvisionForDoubtfulAccounts",
        ],
        "unit": "USD",
        "scale": 1e-6,
    },
    "originations_mm": {
        "tags": [
            "TimeshareFinancingReceivableOriginations",
            "FinancingReceivableOriginatedInCurrentFiscalYear",
            "PaymentsToAcquireNotesReceivable",
        ],
        "unit": "USD",
        "scale": 1e-6,
    },
    "securitized_receivables_mm": {
        "tags": [
            "SecuritizedTimeshareFinancingReceivable",
            "SecuritizedReceivablesFairValueDisclosure",
        ],
        "unit": "USD",
        "scale": 1e-6,
    },
    "gain_on_sale_mm": {
        "tags": [
            "GainLossOnSalesOfLoansNet",
            "GainLossOnSaleOfNotesReceivable",
        ],
        "unit": "USD",
        "scale": 1e-6,
    },
}

# ----- XBRL vintage-pool tag family -----
#
# Timeshare issuers disclose current-year and prior-year origination balances
# as a family of us-gaap tags, one per vintage-year offset from the latest
# fiscal year. When present we stitch them into the structured vintage_pools
# array so the dashboard has at least the original_balance_mm axis even when
# the narrative table is missing (cumulative default rate stays null — that
# lives in the narrative static-pool table only).
XBRL_VINTAGE_TAG_OFFSETS: list[tuple[str, int]] = [
    ("FinancingReceivableOriginatedInCurrentFiscalYear", 0),
    ("FinancingReceivableOriginatedInFiscalYearBeforeLatestFiscalYear", 1),
    ("FinancingReceivableOriginatedTwoYearsBeforeLatestFiscalYear", 2),
    ("FinancingReceivableOriginatedThreeYearsBeforeLatestFiscalYear", 3),
    ("FinancingReceivableOriginatedFourYearsBeforeLatestFiscalYear", 4),
    ("FinancingReceivableOriginatedFiveOrMoreYearsBeforeLatestFiscalYear", 5),
]

# ----- Narrative section locator patterns -----
#
# Each section maps to a list of case-insensitive keyword regexes. A section is
# considered located when any keyword matches the stripped filing text; the
# fetcher then captures a bounded window around the first match.

NARRATIVE_SECTION_PATTERNS: dict[str, list[str]] = {
    "delinquency": [r"delinqu", r"past due", r"aging"],
    "fico": [r"\bFICO\b", r"credit score"],
    "vintage": [
        r"vintage",
        r"static pool",
        r"Origination Year",
        r"year of origination",
        r"originated in",
        r"Vintage Origination",
    ],
    "management_commentary": [
        r"Critical Accounting",
        r"Credit Losses",
        r"Allowance for",
    ],
    "portfolio_segments": [
        r"Legacy[- ]HGV", r"Legacy[- ]Diamond", r"Bluegreen",
        r"Vistana", r"Welk", r"Margaritaville",
        r"acquired\s+(?:timeshare|vacation)\s+(?:financing|receivable)",
        r"originated\s+(?:timeshare|vacation)\s+(?:financing|receivable)",
        r"portfolio\s+segment",
    ],
    "balance_sheet": [
        r"Timeshare financing receivables",
        r"vacation ownership notes receivable",
        r"Notes receivable, net",
        r"Allowance for (credit losses|loan losses|financing receivable)",
        r"Financing receivables",
    ],
}

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
