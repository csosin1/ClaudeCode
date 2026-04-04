"""Parse Servicer Certificate (Exhibit 99.1) HTML for pool-level performance data.

Carvana servicer reports come in two formats:
1. HTML tables (pre-mid-2023, filed via Donnelley): parsed with BeautifulSoup table logic
2. Embedded text in <font> tags alongside JPG images (mid-2023+, filed via Workiva):
   All data is hidden as white-on-white text with numbered fields like:
   (1) Beginning Pool Balance (1) 5,401 20,294,118.53

Both formats use numbered field labels: (1), (2), ... (118+).
"""

import logging
import re
from typing import Optional
from bs4 import BeautifulSoup

from carvana_abs.db.schema import get_connection

logger = logging.getLogger(__name__)


def _clean_number(text: str) -> Optional[float]:
    """Clean a number string from HTML."""
    if not text:
        return None
    text = text.strip()
    if text in ("", "-", "N/A", "n/a", "--", "\u2014"):
        return None
    is_negative = text.startswith("(") and text.endswith(")")
    text = text.replace("(", "").replace(")", "")
    text = text.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        val = float(text)
        return -val if is_negative else val
    except ValueError:
        return None


def _extract_numbered_fields(text: str) -> dict:
    """Extract all numbered fields from servicer report text.

    Handles TWO formats:
    1. Workiva (2023+): (N) Label text (N) Value  — number appears twice
    2. Donnelley (pre-2023): Label text (N) Value  — number appears once after label
       Note: Donnelley HTML can split (105) across cells as "(105 )" with a space.

    Returns: {1: {"label": "...", "raw": "value string"}, ...}
    """
    # Pre-clean: normalize "(105 )" to "(105)" and "8.20 %" to "8.20%"
    text = re.sub(r'\(\s*(\d+)\s*\)', r'(\1)', text)
    text = re.sub(r'(\d)\s+%', r'\1%', text)

    fields = {}

    # Strategy 1: Workiva double-number format: (N) label (N) value
    pattern1 = re.compile(r'\((\d+)\)\s*(.*?)\s*\(\1\)\s+(.*?)(?=\(\d+\)|\Z)', re.DOTALL)
    for match in pattern1.finditer(text):
        field_num = int(match.group(1))
        label = match.group(2).strip()
        value_str = match.group(3).strip()
        fields[field_num] = {"label": label, "raw": value_str}

    # If we found fields with Strategy 1, we're done
    if fields:
        return fields

    # Strategy 2: Donnelley single-number format: label (N) value
    pattern2 = re.compile(r'(?:^|(?<=\s))\((\d+)\)\s+(.*?)(?=\(\d+\)|\Z)', re.DOTALL)
    for match in pattern2.finditer(text):
        field_num = int(match.group(1))
        value_str = match.group(2).strip()
        if field_num not in fields:
            fields[field_num] = {"label": "", "raw": value_str}

    return fields


def _parse_numbered_value(raw: str, expect_count_and_amount: bool = False) -> dict:
    """Parse a raw value string into numbers.

    Some fields have both a count and amount: "5,401 20,294,118.53"
    Others have just one number: "139,999.54" or "4.48%"
    """
    result = {"value": None, "count": None, "pct": None}
    if not raw:
        return result

    # Check for percentage
    if "%" in raw:
        pct_match = re.search(r'(-?[\d,.]+)%', raw)
        if pct_match:
            result["pct"] = _clean_number(pct_match.group(1))
        return result

    # Extract number tokens from the BEGINNING of the value string.
    # Stop when we hit a word (letter character) that's not part of a number.
    # This avoids grabbing stray numbers from trailing label text like "60 days delinquent".
    tokens = raw.split()
    numbers = []
    for token in tokens:
        cleaned = token.replace(",", "").replace("$", "")
        # Skip range patterns like "31-60", "61-90"
        if re.match(r'^\d+-\d+$', cleaned):
            continue
        # If it looks like a number, add it
        if re.match(r'^-?[\d,]+\.?\d*$', token.replace(",", "")):
            numbers.append(token)
        elif re.match(r'^[a-zA-Z]', token):
            # Hit a word — stop collecting numbers
            break

    if expect_count_and_amount and len(numbers) >= 2:
        # Take the FIRST two numbers: count then amount
        # (avoids grabbing trailing numbers from label text)
        result["count"] = _clean_number(numbers[0])
        result["value"] = _clean_number(numbers[1])
    elif numbers:
        result["value"] = _clean_number(numbers[0])

    return result


def parse_servicer_certificate(html_content: str) -> dict:
    """Parse a Carvana servicer certificate HTML and extract pool performance data.

    Tries multiple parsing strategies and MERGES results — later strategies
    fill in fields that earlier ones missed.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    best_result = {}

    # Strategy 1: Embedded <font> text (Workiva format, 2023+)
    font_tags = soup.find_all("font")
    all_font_text = " ".join(f.get_text(separator=" ", strip=True) for f in font_tags)
    if len(all_font_text) > 500:
        result = _parse_from_numbered_text(all_font_text)
        if result.get("distribution_date"):
            best_result = result

    # Strategy 2: All page text with numbered field parser
    if not best_result.get("distribution_date"):
        all_text = soup.get_text(separator=" ", strip=True)
        if len(all_text) > 500:
            result = _parse_from_numbered_text(all_text)
            if result.get("distribution_date"):
                # Merge: fill in missing fields
                for k, v in result.items():
                    if v is not None and best_result.get(k) is None:
                        best_result[k] = v

    # Strategy 3: Row-by-row table text extraction
    tables = soup.find_all("table")
    if tables:
        row_texts = []
        for table in tables:
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                row_text = " ".join(c.get_text(strip=True) for c in cells)
                if row_text.strip():
                    row_texts.append(row_text)
        table_text = " ".join(row_texts)
        if len(table_text) > 500:
            result = _parse_from_numbered_text(table_text)
            for k, v in result.items():
                if v is not None and best_result.get(k) is None:
                    best_result[k] = v
            if not best_result.get("distribution_date") and result.get("distribution_date"):
                best_result["distribution_date"] = result["distribution_date"]

        # Strategy 4: Regex table parsing — fills in remaining gaps
        result = _parse_from_tables(tables)
        for k, v in result.items():
            if v is not None and best_result.get(k) is None:
                best_result[k] = v
        if not best_result.get("distribution_date") and result.get("distribution_date"):
            best_result["distribution_date"] = result["distribution_date"]

    if not best_result.get("distribution_date"):
        logger.warning("No parseable content found in servicer certificate")

    # ── Extract waterfall items ──
    # The waterfall section has lines like:
    #   "18 To holders of the certificates, any remaining amounts 8,178,991.69"
    # These use plain numbers (not in parentheses) as priority items.
    all_text = soup.get_text(separator=" ", strip=True)
    # Pre-clean
    all_text = re.sub(r'\(\s*(\d+)\s*\)', r'(\1)', all_text)
    all_text = re.sub(r'(\d)\s+%', r'\1%', all_text)

    # Extract residual cash: various formats across prime and non-prime deals
    # Prime: "18 To holders of the certificates, any remaining amounts XXXX"
    # Non-prime: "To the holders of the Certificates, any remaining amounts XXXX"
    # Also try: "residual" or "remaining amounts" near a dollar amount
    residual_patterns = [
        r'(?:\d+\.?\s+)?[Tt]o\s+(?:the\s+)?holders?\s+of\s+the\s+[Cc]ertificates?,?\s+any\s+remaining\s+amounts?\s+([\d,]+\.?\d*)',
        r'[Rr]esidual\s+(?:[Cc]ash\s+)?(?:[Dd]istribution\s+)?(?:[Aa]mount\s+)?([\d,]+\.?\d*)',
        r'[Rr]emaining\s+[Aa]mounts?\s+(?:to\s+)?(?:the\s+)?(?:[Cc]ertificate)?(?:holders?)?\s*[:\s]?\s*([\d,]+\.?\d*)',
    ]
    for pattern in residual_patterns:
        m = re.search(pattern, all_text)
        if m and _clean_number(m.group(1)):
            best_result["residual_cash"] = _clean_number(m.group(1))
            break

    # Extract total deposited to collection account
    m = re.search(r'[Tt]otal\s+[Dd]eposited\s+to\s+[Cc]ollection\s+[Aa]ccount\s+([\d,]+\.?\d*)', all_text)
    if m:
        best_result["total_deposited"] = _clean_number(m.group(1))

    # Extract available funds
    m = re.search(r'[Aa]vailable\s+[Ff]unds\s+([\d,]+\.?\d*)', all_text)
    if m:
        best_result["available_funds"] = _clean_number(m.group(1))

    # Extract servicing fee paid (from waterfall, not the loan-level estimate)
    m = re.search(r'[Ss]ervicing\s+[Ff]ee\s+(?:[Pp]ayable\s+)?(?:from\s+)?(?:[Ss]ervicing\s+)?(?:[Ss]trip\s+)?(?:[Aa]mount\s+)?([\d,]+\.?\d*)', all_text)
    if m and _clean_number(m.group(1)):
        best_result["actual_servicing_fee"] = _clean_number(m.group(1))

    # Extract total note interest (sum of all class interest distributable amounts)
    # Pattern: "Class X Interest Distributable Amount XXXX"
    # Deduplicate by class name — servicer certs often repeat amounts in multiple sections
    note_interest_by_class = {}
    for m in re.finditer(r'[Cc]lass\s+(\S+)\s+[Ii]nterest\s+[Dd]istributable\s+[Aa]mount\s+([\d,]+\.?\d*)', all_text):
        cls_name = m.group(1).upper()
        val = _clean_number(m.group(2))
        if val and val > 0:
            # Sanity: monthly interest per class should be < $5M for auto ABS
            if val > 5_000_000:
                logger.warning(f"  note_interest: Class {cls_name} = ${val:,.2f} — too large, likely a balance not interest. Skipping.")
                continue
            note_interest_by_class[cls_name] = val  # Last match per class wins
    note_interest_total = sum(note_interest_by_class.values())
    if note_interest_total > 0:
        best_result["total_note_interest"] = note_interest_total
        logger.debug(f"  note_interest: {note_interest_by_class} total=${note_interest_total:,.2f}")

    # Extract Regular PDA (principal distribution amount)
    m = re.search(r'[Rr]egular\s+PDA\s+(?:\(other\s+than\s+[^)]*\)\s+)?([\d,]+\.?\d*)', all_text)
    if m:
        best_result["regular_pda"] = _clean_number(m.group(1))

    return best_result


def _parse_from_numbered_text(text: str) -> dict:
    """Parse servicer report from numbered field text (Workiva format)."""
    fields = _extract_numbered_fields(text)
    if not fields:
        logger.warning("No numbered fields found in text")
        return {}

    data = {}

    # --- Distribution Date ---
    date_match = re.search(r'Distribution\s+Date:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
    if date_match:
        data["distribution_date"] = date_match.group(1)

    # --- Pool Balance (fields 1, 9) ---
    if 1 in fields:
        v = _parse_numbered_value(fields[1]["raw"], expect_count_and_amount=True)
        data["beginning_pool_balance"] = v["value"]
        data["beginning_pool_count"] = int(v["count"]) if v["count"] else None
    if 9 in fields:
        v = _parse_numbered_value(fields[9]["raw"], expect_count_and_amount=True)
        data["ending_pool_balance"] = v["value"]
        data["ending_pool_count"] = int(v["count"]) if v["count"] else None

    # --- Collections (fields 5, 10, 11, 12) ---
    if 5 in fields:
        v = _parse_numbered_value(fields[5]["raw"], expect_count_and_amount=True)
        data["principal_collections"] = v["value"]
    if 10 in fields:
        data["interest_collections"] = _parse_numbered_value(fields[10]["raw"])["value"]
    if 11 in fields:
        data["recoveries"] = _parse_numbered_value(fields[11]["raw"])["value"]

    # --- Losses (fields 8, 89-98) ---
    if 8 in fields:
        v = _parse_numbered_value(fields[8]["raw"], expect_count_and_amount=True)
        data["gross_charged_off_amount"] = v["value"]
    if 90 in fields:
        data["gross_charged_off_amount"] = data.get("gross_charged_off_amount") or _parse_numbered_value(fields[90]["raw"])["value"]
    if 91 in fields:
        data["cumulative_gross_losses"] = _parse_numbered_value(fields[91]["raw"])["value"]
    if 93 in fields:
        data["liquidation_proceeds"] = _parse_numbered_value(fields[93]["raw"])["value"]
    if 95 in fields:
        data["cumulative_liquidation_proceeds"] = _parse_numbered_value(fields[95]["raw"])["value"]
    if 97 in fields:
        data["net_charged_off_amount"] = _parse_numbered_value(fields[97]["raw"])["value"]
    if 98 in fields:
        data["cumulative_net_losses"] = _parse_numbered_value(fields[98]["raw"])["value"]

    # --- Delinquency (fields 99-104) ---
    if 99 in fields:
        v = _parse_numbered_value(fields[99]["raw"], expect_count_and_amount=True)
        data["delinquent_31_60_count"] = int(v["count"]) if v["count"] else None
        data["delinquent_31_60_balance"] = v["value"]
    if 100 in fields:
        v = _parse_numbered_value(fields[100]["raw"], expect_count_and_amount=True)
        data["delinquent_61_90_count"] = int(v["count"]) if v["count"] else None
        data["delinquent_61_90_balance"] = v["value"]
    if 101 in fields:
        v = _parse_numbered_value(fields[101]["raw"], expect_count_and_amount=True)
        data["delinquent_91_120_count"] = int(v["count"]) if v["count"] else None
        data["delinquent_91_120_balance"] = v["value"]
    if 102 in fields:
        v = _parse_numbered_value(fields[102]["raw"], expect_count_and_amount=True)
        total_dq_count = int(v["count"]) if v["count"] else None
        data["total_delinquent_balance"] = v["value"]
    if 103 in fields:
        data["delinquency_trigger_actual"] = _parse_numbered_value(fields[103]["raw"])["pct"]
        if data["delinquency_trigger_actual"]:
            data["delinquency_trigger_actual"] = data["delinquency_trigger_actual"] / 100.0
    if 104 in fields:
        data["delinquency_trigger_level"] = _parse_numbered_value(fields[104]["raw"])["pct"]
        if data["delinquency_trigger_level"]:
            data["delinquency_trigger_level"] = data["delinquency_trigger_level"] / 100.0

    # --- Note Balances (after monthly payment: fields 20,26,32,38,44,50,56,61) ---
    note_field_map = {
        20: "note_balance_a1", 26: "note_balance_a2", 32: "note_balance_a3",
        38: "note_balance_a4", 44: "note_balance_b", 50: "note_balance_c",
        56: "note_balance_d", 61: "note_balance_n",
    }
    for field_num, col_name in note_field_map.items():
        if field_num in fields:
            data[col_name] = _parse_numbered_value(fields[field_num]["raw"])["value"]

    # --- Note Rates (typically 6 fields before balance: 14,20→14, 26→20 wait...)
    # Standard ABS servicer cert layout per class:
    #   Rate, Interest Distributable, Interest Paid, Shortfall, Balance Before, Principal, Balance After
    # So rate field = balance field - 6
    note_rate_map = {
        14: "note_rate_a1", 20: "note_rate_a2", 26: "note_rate_a3",
        32: "note_rate_a4", 38: "note_rate_b", 44: "note_rate_c",
        50: "note_rate_d", 55: "note_rate_n",
    }
    for field_num, col_name in note_rate_map.items():
        if field_num in fields:
            pct = _parse_numbered_value(fields[field_num]["raw"])["pct"]
            if pct and 0.1 < pct < 30:  # Sanity: rate should be 0.1% to 30%
                data[col_name] = pct / 100.0  # Store as decimal

    # Aggregate note balance (field 76 or sum)
    if 76 in fields:
        data["aggregate_note_balance"] = _parse_numbered_value(fields[76]["raw"])["value"]

    # --- Overcollateralization & Reserve (fields 63, 65, 78, 81) ---
    if 63 in fields:
        data["overcollateralization_amount"] = _parse_numbered_value(fields[63]["raw"])["value"]
    if 78 in fields:
        data["reserve_account_balance"] = _parse_numbered_value(fields[78]["raw"])["value"]
    if 81 in fields:
        data["reserve_account_balance"] = _parse_numbered_value(fields[81]["raw"])["value"]
    if 77 in fields:
        data["specified_reserve_amount"] = _parse_numbered_value(fields[77]["raw"])["value"]

    # --- Pool Statistics (fields 105-112) ---
    if 105 in fields:
        # WAC field has original/prev/current — take current (last number)
        numbers = re.findall(r'[\d.]+%', fields[105]["raw"])
        if numbers:
            pct = _clean_number(numbers[-1].replace("%", ""))
            data["weighted_avg_apr"] = pct / 100.0 if pct else None
    if 106 in fields:
        numbers = re.findall(r'[\d.]+', fields[106]["raw"])
        if numbers:
            data["weighted_avg_remaining_term"] = _clean_number(numbers[-1])
    if 107 in fields:
        numbers = re.findall(r'[\d.]+', fields[107]["raw"])
        if numbers:
            data["weighted_avg_original_term"] = _clean_number(numbers[-1])
    if 108 in fields:
        numbers = re.findall(r'[\d,.]+', fields[108]["raw"])
        if numbers:
            data["avg_principal_balance"] = _clean_number(numbers[-1])

    # --- Extensions (fields 113-114) ---
    if 113 in fields:
        data["extensions_count"] = int(_parse_numbered_value(fields[113]["raw"])["value"] or 0)
    if 114 in fields:
        data["extensions_balance"] = _parse_numbered_value(fields[114]["raw"])["value"]

    return data


def _parse_from_tables(tables) -> dict:
    """Parse servicer report from HTML tables (Donnelley format, pre-2023)."""
    data = {}

    def find_val(pattern, offset=1):
        p = re.compile(pattern, re.IGNORECASE | re.DOTALL)
        for table in tables:
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                for i, cell in enumerate(cells):
                    if p.search(cell.get_text(separator=" ", strip=True)):
                        if i + offset < len(cells):
                            return cells[i + offset].get_text(strip=True)
        return None

    def find_row_vals(pattern):
        p = re.compile(pattern, re.IGNORECASE | re.DOTALL)
        for table in tables:
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                for i, cell in enumerate(cells):
                    if p.search(cell.get_text(separator=" ", strip=True)):
                        return [c.get_text(strip=True) for c in cells[i + 1:]]
        return []

    data["distribution_date"] = find_val(r"distribution\s+date") or find_val(r"payment\s+date")

    # Pool balances
    begin_vals = find_row_vals(r"\(1\)\s*beginning\s+pool|beginning.*pool\s+balance")
    if begin_vals:
        for v in begin_vals:
            num = _clean_number(v)
            if num is not None:
                if num > 100_000:
                    data["beginning_pool_balance"] = num
                else:
                    data["beginning_pool_count"] = int(num)

    end_vals = find_row_vals(r"\(9\)\s*ending\s+pool|ending.*pool\s+balance")
    if end_vals:
        for v in end_vals:
            num = _clean_number(v)
            if num is not None:
                if num > 100_000:
                    data["ending_pool_balance"] = num
                else:
                    data["ending_pool_count"] = int(num)

    data["principal_collections"] = _clean_number(find_val(r"collections?\s+allocable\s+to\s+principal|principal\s+collections"))
    data["interest_collections"] = _clean_number(find_val(r"collections?\s+allocable\s+to\s+interest|interest\s+collections"))
    data["recoveries"] = _clean_number(find_val(r"recover(y|ies)"))
    data["gross_charged_off_amount"] = _clean_number(find_val(r"charged.?off.*current|system.*charged.?off"))
    data["cumulative_net_losses"] = _clean_number(find_val(r"cumulative.*net.*loss|aggregate.*net.*charged"))

    for bucket, pattern in [("31_60", r"31\s*[-\u2013]\s*60"), ("61_90", r"61\s*[-\u2013]\s*90"),
                             ("91_120", r"91\s*[-\u2013]\s*120")]:
        vals = find_row_vals(pattern)
        for v in vals:
            num = _clean_number(v)
            if num is not None:
                if num > 10_000:
                    data[f"delinquent_{bucket}_balance"] = num
                elif data.get(f"delinquent_{bucket}_count") is None:
                    data[f"delinquent_{bucket}_count"] = int(num)

    td_vals = find_row_vals(r"total\s+delinquen")
    for v in td_vals:
        num = _clean_number(v)
        if num is not None and num > 10_000:
            data["total_delinquent_balance"] = num
            break

    data["overcollateralization_amount"] = _clean_number(find_val(r"overcollateral"))
    data["reserve_account_balance"] = _clean_number(find_val(r"reserve\s+account.*balance"))

    # Note balances (after monthly principal payment)
    for note_key, pattern in [
        ("note_balance_a1", r"class\s+a-?1.*(?:note\s+)?balance\s+after"),
        ("note_balance_a2", r"class\s+a-?2.*(?:note\s+)?balance\s+after"),
        ("note_balance_a3", r"class\s+a-?3.*(?:note\s+)?balance\s+after"),
        ("note_balance_a4", r"class\s+a-?4.*(?:note\s+)?balance\s+after"),
        ("note_balance_b", r"class\s+b\b.*(?:note\s+)?balance\s+after"),
        ("note_balance_c", r"class\s+c\b.*(?:note\s+)?balance\s+after"),
        ("note_balance_d", r"class\s+d\b.*(?:note\s+)?balance\s+after"),
        ("note_balance_n", r"class\s+n\b.*(?:note\s+)?balance\s+after"),
    ]:
        val = _clean_number(find_val(pattern))
        if val is not None:
            data[note_key] = val

    # Note rates (from table text)
    for rate_key, pattern in [
        ("note_rate_a1", r"class\s+a-?1\b.*(?:note\s+)?(?:interest\s+)?rate"),
        ("note_rate_a2", r"class\s+a-?2\b.*(?:note\s+)?(?:interest\s+)?rate"),
        ("note_rate_a3", r"class\s+a-?3\b.*(?:note\s+)?(?:interest\s+)?rate"),
        ("note_rate_a4", r"class\s+a-?4\b.*(?:note\s+)?(?:interest\s+)?rate"),
        ("note_rate_b", r"class\s+b\b.*(?:note\s+)?(?:interest\s+)?rate"),
        ("note_rate_c", r"class\s+c\b.*(?:note\s+)?(?:interest\s+)?rate"),
        ("note_rate_d", r"class\s+d\b.*(?:note\s+)?(?:interest\s+)?rate"),
        ("note_rate_n", r"class\s+n\b.*(?:note\s+)?(?:interest\s+)?rate"),
    ]:
        val = _clean_number(find_val(pattern))
        if val is not None:
            if val > 1:  # Percentage, convert to decimal
                val = val / 100.0
            if 0.001 < val < 0.30:  # Sanity: 0.1% to 30%
                data[rate_key] = val

    # WAC, WAM
    data["weighted_avg_apr"] = _clean_number(find_val(r"weighted\s+average\s+apr"))
    if data.get("weighted_avg_apr") and data["weighted_avg_apr"] > 1:
        data["weighted_avg_apr"] = data["weighted_avg_apr"] / 100.0  # Convert from % to decimal
    data["weighted_avg_remaining_term"] = _clean_number(find_val(r"weighted\s+average\s+remaining\s+term"))

    # Cumulative gross losses and liquidation proceeds
    data["cumulative_gross_losses"] = _clean_number(find_val(r"aggregate.*gross.*charged|cumulative.*gross.*loss"))
    data["cumulative_liquidation_proceeds"] = _clean_number(find_val(r"aggregate.*liquidation\s+proceeds"))
    data["net_charged_off_amount"] = _clean_number(find_val(r"net\s+charged.*current|net.*loss.*current"))
    data["liquidation_proceeds"] = _clean_number(find_val(r"gross\s+liquidation.*current|liquidation.*current"))

    # Extensions
    data["extensions_count"] = None
    ext_val = _clean_number(find_val(r"number.*receivables?\s+extended|extensions?\s+.*number"))
    if ext_val is not None:
        data["extensions_count"] = int(ext_val)
    data["extensions_balance"] = _clean_number(find_val(r"principal\s+balance.*receivables?\s+extended|extension.*balance"))

    # Delinquency trigger
    data["delinquency_trigger_actual"] = _clean_number(find_val(r"receivables?\s+greater\s+than\s+60|60.*days?\s+delinquen.*percent"))
    if data.get("delinquency_trigger_actual") and data["delinquency_trigger_actual"] > 1:
        data["delinquency_trigger_actual"] = data["delinquency_trigger_actual"] / 100.0
    data["delinquency_trigger_level"] = _clean_number(find_val(r"delinquency\s+trigger\s+level"))
    if data.get("delinquency_trigger_level") and data["delinquency_trigger_level"] > 1:
        data["delinquency_trigger_level"] = data["delinquency_trigger_level"] / 100.0

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
             cumulative_gross_losses, cumulative_liquidation_proceeds,
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
             extensions_count, extensions_balance,
             residual_cash, total_deposited, available_funds,
             actual_servicing_fee, total_note_interest, regular_pda)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            deal, data["distribution_date"], accession_number,
            data.get("beginning_pool_balance"), data.get("ending_pool_balance"),
            data.get("beginning_pool_count"), data.get("ending_pool_count"),
            data.get("principal_collections"), data.get("interest_collections"),
            data.get("recoveries"),
            data.get("gross_charged_off_amount"), data.get("liquidation_proceeds"),
            data.get("net_charged_off_amount"), data.get("cumulative_net_losses"),
            data.get("cumulative_gross_losses"), data.get("cumulative_liquidation_proceeds"),
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
            data.get("residual_cash"), data.get("total_deposited"),
            data.get("available_funds"), data.get("actual_servicing_fee"),
            data.get("total_note_interest"), data.get("regular_pda"),
        ))

        cursor.execute("UPDATE filings SET ingested_pool = 1 WHERE accession_number = ?",
                        (accession_number,))

        # Populate/update notes table with coupon rates from this cert
        note_class_map = {
            "A1": "note_rate_a1", "A2": "note_rate_a2", "A3": "note_rate_a3",
            "A4": "note_rate_a4", "B": "note_rate_b", "C": "note_rate_c",
            "D": "note_rate_d", "N": "note_rate_n",
        }
        balance_map = {
            "A1": "note_balance_a1", "A2": "note_balance_a2", "A3": "note_balance_a3",
            "A4": "note_balance_a4", "B": "note_balance_b", "C": "note_balance_c",
            "D": "note_balance_d", "N": "note_balance_n",
        }
        for cls, rate_key in note_class_map.items():
            rate = data.get(rate_key)
            if rate:
                # Ensure notes table exists (may not on first run)
                try:
                    cursor.execute("""
                        INSERT OR REPLACE INTO notes (deal, class, coupon_rate, rate_type)
                        VALUES (?, ?, ?, 'FIXED')
                    """, (deal, cls, rate))
                except Exception:
                    pass  # Table may not exist yet on older DBs

        conn.commit()
        logger.info(f"Stored pool performance data for {deal} / {data['distribution_date']}")
        return True

    except Exception as e:
        logger.error(f"Error storing pool data for {accession_number}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
