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
# CIKs verified via SEC EDGAR company search 2026-04-13. Full CARMX history
# back to 2006-1. ABS-EE (loan-level data) only available for deals issued
# after Reg AB II took effect (Nov 2016) — so 2014-2016 contribute pool-level
# only and 2017+ contribute both pool and loan-level data.
DEALS = {
    # 2014–2016 (pool-level only, no ABS-EE — pre-Reg AB II)
    "2014-1": {"cik": "0001598693", "entity_name": "CarMax Auto Owner Trust 2014-1"},
    "2014-2": {"cik": "0001607082", "entity_name": "CarMax Auto Owner Trust 2014-2"},
    "2014-3": {"cik": "0001615396", "entity_name": "CarMax Auto Owner Trust 2014-3"},
    "2014-4": {"cik": "0001623837", "entity_name": "CarMax Auto Owner Trust 2014-4"},
    "2015-1": {"cik": "0001633241", "entity_name": "CarMax Auto Owner Trust 2015-1"},
    "2015-2": {"cik": "0001640878", "entity_name": "CarMax Auto Owner Trust 2015-2"},
    "2015-3": {"cik": "0001648945", "entity_name": "CarMax Auto Owner Trust 2015-3"},
    "2015-4": {"cik": "0001654861", "entity_name": "CarMax Auto Owner Trust 2015-4"},
    "2016-1": {"cik": "0001662810", "entity_name": "CarMax Auto Owner Trust 2016-1"},
    "2016-2": {"cik": "0001671212", "entity_name": "CarMax Auto Owner Trust 2016-2"},
    "2016-3": {"cik": "0001678507", "entity_name": "CarMax Auto Owner Trust 2016-3"},
    "2016-4": {"cik": "0001686277", "entity_name": "CarMax Auto Owner Trust 2016-4"},
    # 2017–2019 (pool + ABS-EE)
    "2017-1": {"cik": "0001693819", "entity_name": "CarMax Auto Owner Trust 2017-1"},
    "2017-2": {"cik": "0001702777", "entity_name": "CarMax Auto Owner Trust 2017-2"},
    "2017-3": {"cik": "0001710329", "entity_name": "CarMax Auto Owner Trust 2017-3"},
    "2017-4": {"cik": "0001718592", "entity_name": "CarMax Auto Owner Trust 2017-4"},
    "2018-1": {"cik": "0001725618", "entity_name": "CarMax Auto Owner Trust 2018-1"},
    "2018-2": {"cik": "0001734850", "entity_name": "CarMax Auto Owner Trust 2018-2"},
    "2018-3": {"cik": "0001742867", "entity_name": "CarMax Auto Owner Trust 2018-3"},
    "2018-4": {"cik": "0001754008", "entity_name": "CarMax Auto Owner Trust 2018-4"},
    "2019-1": {"cik": "0001762278", "entity_name": "CarMax Auto Owner Trust 2019-1"},
    "2019-2": {"cik": "0001770345", "entity_name": "CarMax Auto Owner Trust 2019-2"},
    "2019-3": {"cik": "0001779026", "entity_name": "CarMax Auto Owner Trust 2019-3"},
    "2019-4": {"cik": "0001788503", "entity_name": "CarMax Auto Owner Trust 2019-4"},
    # 2020+ (already in our DB)
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
    # New (not yet in our DB)
    "2025-2": {"cik": "0002063979", "entity_name": "CarMax Auto Owner Trust 2025-2"},
    "2025-3": {"cik": "0002074530", "entity_name": "CarMax Auto Owner Trust 2025-3"},
    "2025-4": {"cik": "0002089777", "entity_name": "CarMax Auto Owner Trust 2025-4"},
    "2026-1": {"cik": "0002094950", "entity_name": "CarMax Auto Owner Trust 2026-1"},
    "2026-2": {"cik": "0002117307", "entity_name": "CarMax Auto Owner Trust 2026-2"},
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
