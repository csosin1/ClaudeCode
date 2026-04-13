"""Configuration for CarMax ABS (CARMX) data ingestion.

CarMax Auto Owner Trust (CARMX) is CarMax's prime auto loan ABS shelf.
CarMax sells sub-prime originations to third parties rather than
securitizing them, so there is no Non-Prime CarMax shelf to track.
"""

import os

# --- SEC EDGAR Settings (shared with carmax_abs) ---
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "CarMaxABSDashboard/1.0 (your-email@example.com)"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
}

REQUEST_DELAY = 0.15  # SEC throttle: ≤10 req/s
AUTO_LOAN_NS = "http://www.sec.gov/edgar/document/absee/autoloan/assetdata"

# --- Deal Registry ---
# CIKs verified via SEC EDGAR full-text search 2026-04-13.
# All 21 CARMX deals issued 2020-Q1 through 2025-Q1.
DEALS = {
    "2020-1": {"cik": "0001796587", "entity_name": "CarMax Auto Owner Trust 2020-1"},
    "2020-2": {"cik": "0001806211", "entity_name": "CarMax Auto Owner Trust 2020-2"},
    "2020-3": {"cik": "0001814294", "entity_name": "CarMax Auto Owner Trust 2020-3"},
    "2020-4": {"cik": "0001825300", "entity_name": "CarMax Auto Owner Trust 2020-4"},
    "2021-1": {"cik": "0001836214", "entity_name": "CarMax Auto Owner Trust 2021-1"},
    "2021-2": {"cik": "0001851375", "entity_name": "CarMax Auto Owner Trust 2021-2"},
    "2021-3": {"cik": "0001867436", "entity_name": "CarMax Auto Owner Trust 2021-3"},
    "2021-4": {"cik": "0001879747", "entity_name": "CarMax Auto Owner Trust 2021-4"},
    "2022-1": {"cik": "0001899236", "entity_name": "CarMax Auto Owner Trust 2022-1"},
    "2022-2": {"cik": "0001921745", "entity_name": "CarMax Auto Owner Trust 2022-2"},
    "2022-3": {"cik": "0001934479", "entity_name": "CarMax Auto Owner Trust 2022-3"},
    "2022-4": {"cik": "0001946521", "entity_name": "CarMax Auto Owner Trust 2022-4"},
    "2023-1": {"cik": "0001959426", "entity_name": "CarMax Auto Owner Trust 2023-1"},
    "2023-2": {"cik": "0001969339", "entity_name": "CarMax Auto Owner Trust 2023-2"},
    "2023-3": {"cik": "0001980857", "entity_name": "CarMax Auto Owner Trust 2023-3"},
    "2023-4": {"cik": "0001995430", "entity_name": "CarMax Auto Owner Trust 2023-4"},
    "2024-1": {"cik": "0002003263", "entity_name": "CarMax Auto Owner Trust 2024-1"},
    "2024-2": {"cik": "0002016948", "entity_name": "CarMax Auto Owner Trust 2024-2"},
    "2024-3": {"cik": "0002029255", "entity_name": "CarMax Auto Owner Trust 2024-3"},
    "2024-4": {"cik": "0002037519", "entity_name": "CarMax Auto Owner Trust 2024-4"},
    "2025-1": {"cik": "0002049715", "entity_name": "CarMax Auto Owner Trust 2025-1"},
}

DEFAULT_DEAL = "2020-1"
CIK = DEALS[DEFAULT_DEAL]["cik"]
ENTITY_NAME = DEALS[DEFAULT_DEAL]["entity_name"]

# --- Database ---
DB_DIR = os.path.join(os.path.dirname(__file__), "db")
DB_PATH = os.path.join(DB_DIR, "carmax_abs.db")


def get_deal_config(deal_slug: str) -> dict:
    if deal_slug not in DEALS:
        raise ValueError(f"Unknown deal: {deal_slug}. Available: {list(DEALS.keys())}")
    return DEALS[deal_slug]


def get_active_deals() -> list[str]:
    return list(DEALS.keys())
