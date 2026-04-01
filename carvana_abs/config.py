"""Configuration for Carvana ABS data ingestion — supports multiple deals."""

import os

# --- SEC EDGAR Settings ---
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

# SEC requires a descriptive User-Agent with contact info
# Update this with your own name/email before running
USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "CarvanaABSDashboard/1.0 (your-email@example.com)"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
}

# Rate limiting: SEC allows max 10 requests/sec
REQUEST_DELAY = 0.15  # seconds between requests (conservative)

# ABS-EE XML namespace for auto loan data
AUTO_LOAN_NS = "http://www.sec.gov/edgar/document/absee/autoloan/assetdata"

# --- Deal Registry ---
# Each deal is keyed by a short slug used in the DB filename and dashboard selector.
# Carvana ABS deals from SEC EDGAR. "P" series = prime, "N" series = non-prime.
DEALS = {
    # ── 2020 ──
    "2020-P1": {
        "cik": "0001801738",
        "entity_name": "Carvana Auto Receivables Trust 2020-P1",
        "distribution_day": 8,
        "original_pool_balance": 405_000_000,
    },
    # ── 2021 ──
    "2021-N1": {
        "cik": "0001842012",
        "entity_name": "Carvana Auto Receivables Trust 2021-N1",
        "distribution_day": 8,
        "original_pool_balance": None,  # will be set from first servicer cert
    },
    "2021-N2": {
        "cik": "0001843643",
        "entity_name": "Carvana Auto Receivables Trust 2021-N2",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    "2021-N3": {
        "cik": "0001843653",
        "entity_name": "Carvana Auto Receivables Trust 2021-N3",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    "2021-N4": {
        "cik": "0001845211",
        "entity_name": "Carvana Auto Receivables Trust 2021-N4",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    "2021-P1": {
        "cik": "0001841341",
        "entity_name": "Carvana Auto Receivables Trust 2021-P1",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    "2021-P2": {
        "cik": "0001843657",
        "entity_name": "Carvana Auto Receivables Trust 2021-P2",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    # ── 2022 ──
    "2022-P1": {
        "cik": "0001903763",
        "entity_name": "Carvana Auto Receivables Trust 2022-P1",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    "2022-P2": {
        "cik": "0001903753",
        "entity_name": "Carvana Auto Receivables Trust 2022-P2",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    "2022-P3": {
        "cik": "0001903756",
        "entity_name": "Carvana Auto Receivables Trust 2022-P3",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    # ── 2023 ──
    "2023-P5": {
        "cik": "0001967527",
        "entity_name": "Carvana Auto Receivables Trust 2023-P5",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    # ── 2024 ──
    "2024-N1": {
        "cik": "0001903764",
        "entity_name": "Carvana Auto Receivables Trust 2024-N1",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    "2024-P2": {
        "cik": "0001999671",
        "entity_name": "Carvana Auto Receivables Trust 2024-P2",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    "2024-P3": {
        "cik": "0001999856",
        "entity_name": "Carvana Auto Receivables Trust 2024-P3",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    "2024-P4": {
        "cik": "0001999854",
        "entity_name": "Carvana Auto Receivables Trust 2024-P4",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    # ── 2025 ──
    "2025-P2": {
        "cik": "0002037955",
        "entity_name": "Carvana Auto Receivables Trust 2025-P2",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    "2025-P3": {
        "cik": "0002037953",
        "entity_name": "Carvana Auto Receivables Trust 2025-P3",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    "2025-P4": {
        "cik": "0002037952",
        "entity_name": "Carvana Auto Receivables Trust 2025-P4",
        "distribution_day": 8,
        "original_pool_balance": None,
    },
    # NOTE: Some deals are missing (2022-N1, 2023-P1 through P4, 2023-N series,
    # 2024-P1, 2025-P1, 2025-N series). Their CIKs weren't found in web search.
    # They can be discovered by searching SEC EDGAR directly:
    # https://www.sec.gov/cgi-bin/browse-edgar?company=carvana+auto+receivables&CIK=&type=&dateb=&owner=include&count=100
}

# Default deal for backward compatibility
DEFAULT_DEAL = "2020-P1"
CIK = DEALS[DEFAULT_DEAL]["cik"]
ENTITY_NAME = DEALS[DEFAULT_DEAL]["entity_name"]

# --- Database ---
DB_DIR = os.path.join(os.path.dirname(__file__), "db")
DB_PATH = os.path.join(DB_DIR, "carvana_abs.db")  # single DB for all deals


def get_deal_config(deal_slug: str) -> dict:
    """Get configuration for a specific deal by its slug (e.g., '2020-P1')."""
    if deal_slug not in DEALS:
        raise ValueError(f"Unknown deal: {deal_slug}. Available: {list(DEALS.keys())}")
    return DEALS[deal_slug]


def get_active_deals() -> list[str]:
    """Return list of active deal slugs (uncommented in DEALS)."""
    return list(DEALS.keys())
