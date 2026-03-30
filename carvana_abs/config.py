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
# Add new Carvana deals here as needed.
DEALS = {
    "2020-P1": {
        "cik": "0001801738",
        "entity_name": "Carvana Auto Receivables Trust 2020-P1",
        "closing_date": "2020-12-10",
        "distribution_day": 8,
        "original_pool_balance": 405_000_000,  # approximate from prospectus
        "note_classes": ["A-1", "A-2", "A-3", "A-4", "B", "C", "D", "N"],
    },
    # Future deals — uncomment or add as needed:
    # "2021-N1": {
    #     "cik": "0001841341",
    #     "entity_name": "Carvana Auto Receivables Trust 2021-N1",
    #     "closing_date": "2021-03-17",
    #     "distribution_day": 8,
    #     "original_pool_balance": 500_000_000,
    #     "note_classes": ["A", "B", "C", "D", "E", "N"],
    # },
    # "2021-P1": {
    #     "cik": "0001841341",  # verify CIK
    #     "entity_name": "Carvana Auto Receivables Trust 2021-P1",
    #     "closing_date": "2021-05-12",
    #     "distribution_day": 8,
    #     "original_pool_balance": 550_000_000,
    #     "note_classes": ["A-1", "A-2", "A-3", "A-4", "B", "C", "D", "N"],
    # },
    # "2022-P1": {
    #     "cik": "0001903763",
    #     "entity_name": "Carvana Auto Receivables Trust 2022-P1",
    #     "closing_date": "2022-09-14",
    #     "distribution_day": 8,
    #     "original_pool_balance": 600_000_000,
    #     "note_classes": ["A-1", "A-2", "A-3", "A-4", "B", "C", "D", "N"],
    # },
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
