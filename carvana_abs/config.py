"""Configuration for Carvana 2020-P1 ABS data ingestion."""

import os

# SEC EDGAR settings
CIK = "0001801738"
ENTITY_NAME = "Carvana Auto Receivables Trust 2020-P1"
SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"
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

# Database
DB_DIR = os.path.join(os.path.dirname(__file__), "db")
DB_PATH = os.path.join(DB_DIR, "carvana_2020p1.db")

# Trust details
TRUST_CLOSING_DATE = "2020-12-10"
DISTRIBUTION_DAY = 8  # 8th of each month

# ABS-EE XML namespace for auto loan data
AUTO_LOAN_NS = "http://www.sec.gov/edgar/document/absee/autoloan/assetdata"
