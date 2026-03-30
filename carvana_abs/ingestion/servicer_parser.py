"""Parse Servicer Certificate (Exhibit 99.1) HTML for pool-level performance data."""

import logging
import re
from typing import Optional
from bs4 import BeautifulSoup

from carvana_abs.db.schema import get_connection

logger = logging.getLogger(__name__)


def _clean_number(text: str) -> Optional[float]:
    """Clean a number string from HTML (remove $, commas, parens for negatives)."""
    if not text:
        return None
    text = text.strip()
    if text in ("", "-", "N/A", "n/a", "--"):
        return None

    # Handle parentheses for negative numbers: (1,234.56) -> -1234.56
    is_negative = text.startswith("(") and text.endswith(")")
    text = text.replace("(", "").replace(")", "")
    text = text.replace("$", "").replace(",", "").replace("%", "").strip()

    try:
        val = float(text)
        return -val if is_negative else val
    except ValueError:
        return None


def _clean_int(text: str) -> Optional[int]:
    """Clean an integer string from HTML."""
    val = _clean_number(text)
    return int(val) if val is not None else None


def _find_value_in_tables(tables, label_pattern: str, value_offset: int = 1) -> Optional[str]:
    """Search all tables for a row matching label_pattern and return the value cell.

    Args:
        tables: List of BeautifulSoup table elements.
        label_pattern: Regex pattern to match in the label cell.
        value_offset: Which cell after the label to use as value (default 1 = next cell).
    """
    pattern = re.compile(label_pattern, re.IGNORECASE)
    for table in tables:
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            for i, cell in enumerate(cells):
                cell_text = cell.get_text(strip=True)
                if pattern.search(cell_text):
                    target_idx = i + value_offset
                    if target_idx < len(cells):
                        return cells[target_idx].get_text(strip=True)
    return None


def _find_all_values_in_tables(tables, label_pattern: str) -> list[str]:
    """Find all value cells matching a label pattern across all tables."""
    pattern = re.compile(label_pattern, re.IGNORECASE)
    results = []
    for table in tables:
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            for i, cell in enumerate(cells):
                cell_text = cell.get_text(strip=True)
                if pattern.search(cell_text):
                    # Collect all subsequent value cells in this row
                    for j in range(i + 1, len(cells)):
                        val = cells[j].get_text(strip=True)
                        if val and val not in ("", "-"):
                            results.append(val)
                    break
    return results


def _extract_date(tables, label_pattern: str) -> Optional[str]:
    """Extract a date value from tables matching a label."""
    val = _find_value_in_tables(tables, label_pattern)
    if val:
        # Try to normalize date formats
        val = val.strip()
        # Common formats: "January 8, 2021", "01/08/2021", "2021-01-08"
        return val
    return None


def parse_servicer_certificate(html_content: str) -> dict:
    """Parse a servicer certificate HTML document and extract pool performance data.

    Returns a dict of pool performance metrics.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    tables = soup.find_all("table")

    if not tables:
        logger.warning("No tables found in servicer certificate HTML")
        return {}

    data = {}

    # Distribution Date
    data["distribution_date"] = _extract_date(tables, r"distribution\s+date")

    # Pool Balance
    data["beginning_pool_balance"] = _clean_number(
        _find_value_in_tables(tables, r"beginning\s+(aggregate\s+)?pool\s+balance|beginning\s+principal\s+balance")
    )
    data["ending_pool_balance"] = _clean_number(
        _find_value_in_tables(tables, r"ending\s+(aggregate\s+)?pool\s+balance|ending\s+principal\s+balance")
    )

    # Pool Count
    data["beginning_pool_count"] = _clean_int(
        _find_value_in_tables(tables, r"beginning.*(number|count|units)")
    )
    data["ending_pool_count"] = _clean_int(
        _find_value_in_tables(tables, r"ending.*(number|count|units)")
    )

    # Collections
    data["principal_collections"] = _clean_number(
        _find_value_in_tables(tables, r"(total\s+)?collections?\s+allocable\s+to\s+principal|principal\s+collections")
    )
    data["interest_collections"] = _clean_number(
        _find_value_in_tables(tables, r"(total\s+)?collections?\s+allocable\s+to\s+interest|interest\s+collections")
    )
    data["recoveries"] = _clean_number(
        _find_value_in_tables(tables, r"recover(y|ies)")
    )

    # Losses
    data["charged_off_amount"] = _clean_number(
        _find_value_in_tables(tables, r"charged.?off.*(loss|amount|principal).*current|current.*charged.?off")
    )
    data["cumulative_net_losses"] = _clean_number(
        _find_value_in_tables(tables, r"cumulative.*net.*loss")
    )

    # Delinquency buckets
    data["delinquent_31_60_balance"] = _clean_number(
        _find_value_in_tables(tables, r"31\s*[-–]\s*60\s*day")
    )
    data["delinquent_61_90_balance"] = _clean_number(
        _find_value_in_tables(tables, r"61\s*[-–]\s*90\s*day")
    )
    data["delinquent_91_120_balance"] = _clean_number(
        _find_value_in_tables(tables, r"91\s*[-–]\s*120\s*day")
    )
    data["delinquent_121_plus_balance"] = _clean_number(
        _find_value_in_tables(tables, r"12[01]\s*\+\s*day|over\s*120|121")
    )

    # Total delinquencies
    data["total_delinquent_balance"] = _clean_number(
        _find_value_in_tables(tables, r"total\s+delinquen")
    )

    # Delinquency counts (may or may not be available)
    data["delinquent_31_60_count"] = _clean_int(
        _find_value_in_tables(tables, r"31\s*[-–]\s*60\s*day.*count|31\s*[-–]\s*60\s*day.*number")
    )
    data["delinquent_61_90_count"] = _clean_int(
        _find_value_in_tables(tables, r"61\s*[-–]\s*90\s*day.*count|61\s*[-–]\s*90\s*day.*number")
    )
    data["delinquent_91_120_count"] = _clean_int(
        _find_value_in_tables(tables, r"91\s*[-–]\s*120\s*day.*count|91\s*[-–]\s*120\s*day.*number")
    )
    data["delinquent_121_plus_count"] = _clean_int(
        _find_value_in_tables(tables, r"12[01]\s*\+.*count|over\s*120.*count|121.*count")
    )

    # Note balances
    for note_class, pattern in [
        ("note_balance_a1", r"class\s+a-?1.*balance|a-?1.*note.*balance"),
        ("note_balance_a2", r"class\s+a-?2.*balance|a-?2.*note.*balance"),
        ("note_balance_a3", r"class\s+a-?3.*balance|a-?3.*note.*balance"),
        ("note_balance_a4", r"class\s+a-?4.*balance|a-?4.*note.*balance"),
        ("note_balance_b", r"class\s+b\b.*balance|(?<!\w)b\s+note.*balance"),
        ("note_balance_c", r"class\s+c\b.*balance|(?<!\w)c\s+note.*balance"),
        ("note_balance_d", r"class\s+d\b.*balance|(?<!\w)d\s+note.*balance"),
    ]:
        data[note_class] = _clean_number(
            _find_value_in_tables(tables, pattern)
        )

    # Overcollateralization and reserve
    data["overcollateralization_amount"] = _clean_number(
        _find_value_in_tables(tables, r"overcollateral")
    )
    data["reserve_account_balance"] = _clean_number(
        _find_value_in_tables(tables, r"reserve\s+account.*balance|specified\s+reserve")
    )

    return data


def store_pool_data(html_content: str, accession_number: str, db_path: Optional[str] = None) -> bool:
    """Parse servicer certificate HTML and store pool performance data.

    Returns True if data was successfully stored.
    """
    from carvana_abs.config import DB_PATH

    data = parse_servicer_certificate(html_content)
    if not data or not data.get("distribution_date"):
        logger.warning(f"Could not parse servicer certificate for {accession_number}")
        return False

    conn = get_connection(db_path or DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT OR REPLACE INTO pool_performance
            (distribution_date, accession_number,
             beginning_pool_balance, ending_pool_balance,
             beginning_pool_count, ending_pool_count,
             principal_collections, interest_collections, recoveries,
             charged_off_amount, cumulative_net_losses,
             delinquent_31_60_balance, delinquent_61_90_balance,
             delinquent_91_120_balance, delinquent_121_plus_balance,
             total_delinquent_balance,
             delinquent_31_60_count, delinquent_61_90_count,
             delinquent_91_120_count, delinquent_121_plus_count,
             note_balance_a1, note_balance_a2, note_balance_a3, note_balance_a4,
             note_balance_b, note_balance_c, note_balance_d,
             overcollateralization_amount, reserve_account_balance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["distribution_date"], accession_number,
            data.get("beginning_pool_balance"), data.get("ending_pool_balance"),
            data.get("beginning_pool_count"), data.get("ending_pool_count"),
            data.get("principal_collections"), data.get("interest_collections"),
            data.get("recoveries"),
            data.get("charged_off_amount"), data.get("cumulative_net_losses"),
            data.get("delinquent_31_60_balance"), data.get("delinquent_61_90_balance"),
            data.get("delinquent_91_120_balance"), data.get("delinquent_121_plus_balance"),
            data.get("total_delinquent_balance"),
            data.get("delinquent_31_60_count"), data.get("delinquent_61_90_count"),
            data.get("delinquent_91_120_count"), data.get("delinquent_121_plus_count"),
            data.get("note_balance_a1"), data.get("note_balance_a2"),
            data.get("note_balance_a3"), data.get("note_balance_a4"),
            data.get("note_balance_b"), data.get("note_balance_c"),
            data.get("note_balance_d"),
            data.get("overcollateralization_amount"), data.get("reserve_account_balance"),
        ))

        # Mark filing as pool-ingested
        cursor.execute("""
            UPDATE filings SET ingested_pool = 1 WHERE accession_number = ?
        """, (accession_number,))

        conn.commit()
        logger.info(f"Stored pool performance data for {data['distribution_date']}")
        return True

    except Exception as e:
        logger.error(f"Error storing pool data for {accession_number}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
