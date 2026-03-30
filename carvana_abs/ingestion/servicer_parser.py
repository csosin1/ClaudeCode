"""Parse Servicer Certificate (Exhibit 99.1) HTML for pool-level performance data.

Tuned for Carvana Auto Receivables Trust servicer report format, which uses
numbered line items like:
  (1) Beginning Pool Balance (units / $)
  (5) Total collections allocable to principal
  (8) Charged-Off Losses
  (9) Ending Pool Balance
  (10) Collections allocable to interest
  (11) Recoveries
  ...with delinquency buckets (31-60, 61-90, 91-120 days) and trigger levels.
"""

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
    if text in ("", "-", "N/A", "n/a", "--", "—"):
        return None

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
    """Search all tables for a row matching label_pattern and return the value cell."""
    pattern = re.compile(label_pattern, re.IGNORECASE | re.DOTALL)
    for table in tables:
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            for i, cell in enumerate(cells):
                cell_text = cell.get_text(separator=" ", strip=True)
                if pattern.search(cell_text):
                    target_idx = i + value_offset
                    if target_idx < len(cells):
                        return cells[target_idx].get_text(strip=True)
    return None


def _find_row_values(tables, label_pattern: str) -> list[str]:
    """Find all value cells in the same row as a label match."""
    pattern = re.compile(label_pattern, re.IGNORECASE | re.DOTALL)
    for table in tables:
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            for i, cell in enumerate(cells):
                cell_text = cell.get_text(separator=" ", strip=True)
                if pattern.search(cell_text):
                    return [c.get_text(strip=True) for c in cells[i + 1:]]
    return []


def parse_servicer_certificate(html_content: str) -> dict:
    """Parse a Carvana servicer certificate HTML and extract pool performance data.

    Note: Carvana switched from HTML tables to embedded JPG images around 2023.
    This parser only works with the HTML table format (pre-2023 filings).
    JPG-based filings will return an empty dict.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    tables = soup.find_all("table")

    if not tables:
        # Check if this is a JPG-based filing (Carvana switched ~2023)
        imgs = soup.find_all("img")
        if imgs:
            logger.info("Servicer certificate is image-based (JPG) — skipping (requires OCR)")
        else:
            logger.warning("No tables or images found in servicer certificate HTML")
        return {}

    data = {}

    # --- Distribution Date ---
    data["distribution_date"] = (
        _find_value_in_tables(tables, r"distribution\s+date") or
        _find_value_in_tables(tables, r"payment\s+date")
    )

    # --- Pool Balance Rollforward ---
    # Carvana format: "(1) Beginning Pool Balance" with units and $ in separate columns
    # Try to get both units and dollar amount
    begin_vals = _find_row_values(tables, r"\(1\)\s*beginning\s+pool\s+balance|beginning\s+(aggregate\s+)?pool\s+balance")
    if begin_vals:
        # Usually: [units, $amount] or just [$amount]
        for v in begin_vals:
            num = _clean_number(v)
            if num is not None:
                if num > 100_000:  # dollar amount (not a count)
                    data["beginning_pool_balance"] = num
                else:
                    data["beginning_pool_count"] = int(num)

    end_vals = _find_row_values(tables, r"\(9\)\s*ending\s+pool\s+balance|ending\s+(aggregate\s+)?pool\s+balance")
    if end_vals:
        for v in end_vals:
            num = _clean_number(v)
            if num is not None:
                if num > 100_000:
                    data["ending_pool_balance"] = num
                else:
                    data["ending_pool_count"] = int(num)

    # Fallback: try without numbered prefixes
    if "beginning_pool_balance" not in data:
        data["beginning_pool_balance"] = _clean_number(
            _find_value_in_tables(tables, r"beginning.*principal\s+balance|beginning.*pool\s+balance")
        )
    if "ending_pool_balance" not in data:
        data["ending_pool_balance"] = _clean_number(
            _find_value_in_tables(tables, r"ending.*principal\s+balance|ending.*pool\s+balance")
        )

    # --- Collections ---
    data["principal_collections"] = _clean_number(
        _find_value_in_tables(tables, r"\(5\)\s*total\s+collections\s+allocable\s+to\s+principal|collections?\s+allocable\s+to\s+principal|principal\s+collections")
    )
    data["interest_collections"] = _clean_number(
        _find_value_in_tables(tables, r"\(10\)\s*collections?\s+allocable\s+to\s+interest|collections?\s+allocable\s+to\s+interest|interest\s+collections")
    )
    data["recoveries"] = _clean_number(
        _find_value_in_tables(tables, r"\(11\)\s*collections?\s+from\s+recover|recover(y|ies)")
    )

    # --- Losses ---
    data["gross_charged_off_amount"] = _clean_number(
        _find_value_in_tables(tables, r"\(8\)\s*charged.?off|gross\s+charged.?off|system\s+charged.?off")
    )
    data["liquidation_proceeds"] = _clean_number(
        _find_value_in_tables(tables, r"liquidation\s+proceeds")
    )
    data["net_charged_off_amount"] = _clean_number(
        _find_value_in_tables(tables, r"net\s+charged.?off.*current|net\s+charged.?off.*period|net\s+charged.?off.*loss")
    )
    data["cumulative_net_losses"] = _clean_number(
        _find_value_in_tables(tables, r"cumulative.*net.*loss|cumulative.*charged.?off")
    )

    # --- Delinquency Buckets ---
    # Carvana reports delinquencies with both count and balance
    for bucket, pattern in [
        ("31_60", r"31\s*[-–]\s*60\s*day"),
        ("61_90", r"61\s*[-–]\s*90\s*day"),
        ("91_120", r"91\s*[-–]\s*120\s*day"),
        ("121_plus", r"12[01]\s*\+|over\s*120|121\s*[-–]|greater\s+than\s+120"),
    ]:
        vals = _find_row_values(tables, pattern)
        count_val = None
        balance_val = None
        for v in vals:
            num = _clean_number(v)
            if num is not None:
                if num > 10_000:  # dollar amount
                    balance_val = num
                elif count_val is None:
                    count_val = int(num)
        data[f"delinquent_{bucket}_balance"] = balance_val
        data[f"delinquent_{bucket}_count"] = count_val

    # Total delinquencies
    total_dq_vals = _find_row_values(tables, r"total\s+delinquen")
    for v in total_dq_vals:
        num = _clean_number(v)
        if num is not None and num > 10_000:
            data["total_delinquent_balance"] = num
            break

    # --- Delinquency Trigger ---
    data["delinquency_trigger_level"] = _clean_number(
        _find_value_in_tables(tables, r"delinquency\s+trigger\s+level")
    )
    data["delinquency_trigger_actual"] = _clean_number(
        _find_value_in_tables(tables, r"receivables.*greater\s+than\s+60\s+days|actual\s+delinquency|60\+\s*day.*delinquen.*percent")
    )

    # --- Note Balances ---
    # Try to find note balance table (usually has "Current Note Balance" column)
    for note_class, pattern in [
        ("note_balance_a1", r"(?:class\s+)?a-?1\b"),
        ("note_balance_a2", r"(?:class\s+)?a-?2\b"),
        ("note_balance_a3", r"(?:class\s+)?a-?3\b"),
        ("note_balance_a4", r"(?:class\s+)?a-?4\b"),
        ("note_balance_b", r"(?:class\s+)?(?<![a-z])b\b(?!\w*alanc)"),
        ("note_balance_c", r"(?:class\s+)?(?<![a-z])c\b(?!\w*umul)"),
        ("note_balance_d", r"(?:class\s+)?(?<![a-z])d\b(?!\w*eli)"),
        ("note_balance_n", r"(?:class\s+)?(?<![a-z])n\b(?!\w*ote)"),
    ]:
        # Look in note distribution table for current balance
        data[note_class] = _clean_number(
            _find_value_in_tables(tables, pattern)
        )

    data["aggregate_note_balance"] = _clean_number(
        _find_value_in_tables(tables, r"aggregate\s+note\s+balance|total.*note.*balance")
    )

    # --- Pool Statistics ---
    data["weighted_avg_apr"] = _clean_number(
        _find_value_in_tables(tables, r"weighted\s+average\s+apr|weighted\s+avg.*apr|wa\s*apr")
    )
    data["weighted_avg_remaining_term"] = _clean_number(
        _find_value_in_tables(tables, r"weighted\s+average\s+remaining\s+term|wa.*remaining\s+term")
    )
    data["weighted_avg_original_term"] = _clean_number(
        _find_value_in_tables(tables, r"weighted\s+average\s+original\s+term|wa.*original\s+term")
    )
    data["avg_principal_balance"] = _clean_number(
        _find_value_in_tables(tables, r"average\s+principal\s+balance|avg.*principal\s+bal")
    )

    # --- Overcollateralization & Reserve ---
    data["overcollateralization_amount"] = _clean_number(
        _find_value_in_tables(tables, r"overcollateral")
    )
    data["reserve_account_balance"] = _clean_number(
        _find_value_in_tables(tables, r"reserve\s+account.*balance")
    )
    data["specified_reserve_amount"] = _clean_number(
        _find_value_in_tables(tables, r"specified\s+reserve")
    )

    # --- Extensions ---
    data["extensions_count"] = _clean_int(
        _find_value_in_tables(tables, r"extension.*number|number.*extension|extensions?.*count")
    )
    data["extensions_balance"] = _clean_number(
        _find_value_in_tables(tables, r"extension.*balance|extension.*principal|principal.*extension")
    )

    return data


def store_pool_data(html_content: str, accession_number: str,
                    deal: str, db_path: Optional[str] = None) -> bool:
    """Parse servicer certificate HTML and store pool performance data."""
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
            (deal, distribution_date, accession_number,
             beginning_pool_balance, ending_pool_balance,
             beginning_pool_count, ending_pool_count,
             principal_collections, interest_collections, recoveries,
             gross_charged_off_amount, liquidation_proceeds,
             net_charged_off_amount, cumulative_net_losses,
             delinquent_31_60_balance, delinquent_61_90_balance,
             delinquent_91_120_balance, delinquent_121_plus_balance,
             total_delinquent_balance,
             delinquent_31_60_count, delinquent_61_90_count,
             delinquent_91_120_count, delinquent_121_plus_count,
             delinquency_trigger_level, delinquency_trigger_actual,
             note_balance_a1, note_balance_a2, note_balance_a3, note_balance_a4,
             note_balance_b, note_balance_c, note_balance_d, note_balance_n,
             aggregate_note_balance,
             weighted_avg_apr, weighted_avg_remaining_term,
             weighted_avg_original_term, avg_principal_balance,
             overcollateralization_amount, reserve_account_balance,
             specified_reserve_amount,
             extensions_count, extensions_balance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?)
        """, (
            deal, data["distribution_date"], accession_number,
            data.get("beginning_pool_balance"), data.get("ending_pool_balance"),
            data.get("beginning_pool_count"), data.get("ending_pool_count"),
            data.get("principal_collections"), data.get("interest_collections"),
            data.get("recoveries"),
            data.get("gross_charged_off_amount"), data.get("liquidation_proceeds"),
            data.get("net_charged_off_amount"), data.get("cumulative_net_losses"),
            data.get("delinquent_31_60_balance"), data.get("delinquent_61_90_balance"),
            data.get("delinquent_91_120_balance"), data.get("delinquent_121_plus_balance"),
            data.get("total_delinquent_balance"),
            data.get("delinquent_31_60_count"), data.get("delinquent_61_90_count"),
            data.get("delinquent_91_120_count"), data.get("delinquent_121_plus_count"),
            data.get("delinquency_trigger_level"), data.get("delinquency_trigger_actual"),
            data.get("note_balance_a1"), data.get("note_balance_a2"),
            data.get("note_balance_a3"), data.get("note_balance_a4"),
            data.get("note_balance_b"), data.get("note_balance_c"),
            data.get("note_balance_d"), data.get("note_balance_n"),
            data.get("aggregate_note_balance"),
            data.get("weighted_avg_apr"), data.get("weighted_avg_remaining_term"),
            data.get("weighted_avg_original_term"), data.get("avg_principal_balance"),
            data.get("overcollateralization_amount"), data.get("reserve_account_balance"),
            data.get("specified_reserve_amount"),
            data.get("extensions_count"), data.get("extensions_balance"),
        ))

        cursor.execute("""
            UPDATE filings SET ingested_pool = 1 WHERE accession_number = ?
        """, (accession_number,))

        conn.commit()
        logger.info(f"Stored pool performance data for {deal} / {data['distribution_date']}")
        return True

    except Exception as e:
        logger.error(f"Error storing pool data for {accession_number}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
