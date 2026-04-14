"""Parse Servicer Certificate (Exhibit 99.1) HTML for pool-level performance data.

Carvana servicer reports come in two formats:
1. HTML tables (pre-mid-2023, filed via Donnelley): parsed with BeautifulSoup table logic
2. Embedded text in <font> tags alongside JPG images (mid-2023+, filed via Workiva):
   All data is hidden as white-on-white text with numbered fields like:
   (1) Beginning Pool Balance (1) 5,401 20,294,118.53

Both formats use numbered field labels: (1), (2), ... (118+).
"""

import logging
import os
import re
from datetime import datetime, date
from typing import Optional, Tuple
from bs4 import BeautifulSoup

from carvana_abs.db.schema import get_connection

logger = logging.getLogger(__name__)

# Dedicated audit log for ingestion collision + stale-header decisions.
# Lives next to the DB so it's visible for post-mortems without cluttering stderr.
_AUDIT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "db",
    "ingestion_decisions.log",
)


def _audit(msg: str) -> None:
    """Append one decision line to the ingestion audit log + info-log it."""
    try:
        os.makedirs(os.path.dirname(_AUDIT_LOG_PATH), exist_ok=True)
        with open(_AUDIT_LOG_PATH, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()}Z {msg}\n")
    except Exception:
        pass
    logger.info(msg)


def _parse_mdy(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%m/%d/%Y").date()
    except (ValueError, TypeError):
        return None


def _parse_ymd(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _is_stale_header(
    data: dict,
    filing_date: Optional[date],
    filing_type: Optional[str],
) -> Tuple[bool, int]:
    """Detect stale-header filings: issuer copied the prior period's
    'Distribution Date' literal into the current cert, so the extracted
    distribution_date disagrees with filing_date by >30 days.

    Amendments (/A) are excluded: they're legitimately filed weeks or months
    after the period they restate. Normal filing lag is ~7-14 days so 30
    days is a safe threshold.

    Returns (is_stale, delta_days)."""
    if filing_date is None:
        return False, 0
    if filing_type and filing_type.endswith("/A"):
        return False, 0
    dist_date = _parse_mdy(data.get("distribution_date"))
    if dist_date is None:
        return False, 0
    delta_days = abs((filing_date - dist_date).days)
    return (delta_days > 30), delta_days


def _resolve_collision(
    conn,
    deal: str,
    distribution_date: str,
    incoming_accession: str,
    incoming_filing_type: Optional[str],
    incoming_filing_date: Optional[date],
) -> Tuple[bool, Optional[str]]:
    """Decide whether incoming filing should overwrite the existing row at
    (deal, distribution_date). Same precedence rules as CarMax side:
      1. Incoming /A + existing plain  -> accept (amendment wins).
      2. Existing /A + incoming plain  -> reject (protect amendment).
      3. Same tier                     -> prefer later filing_date.
      4. No existing row               -> accept.
    """
    row = conn.execute(
        """
        SELECT pp.accession_number, f.filing_type, f.filing_date
        FROM pool_performance pp
        LEFT JOIN filings f ON f.accession_number = pp.accession_number
        WHERE pp.deal = ? AND pp.distribution_date = ?
        """,
        (deal, distribution_date),
    ).fetchone()

    if row is None:
        return True, "no_existing_row"
    # Support both tuple and sqlite3.Row access
    existing_acc = row[0]
    existing_type = row[1]
    existing_fdate_str = row[2]

    if existing_acc == incoming_accession:
        return True, "same_accession_reingest"

    incoming_is_a = bool(incoming_filing_type and incoming_filing_type.endswith("/A"))
    existing_is_a = bool(existing_type and existing_type.endswith("/A"))

    if incoming_is_a and not existing_is_a:
        return True, f"amendment_overwrites_original(existing={existing_acc})"
    if existing_is_a and not incoming_is_a:
        return False, f"refuse_overwrite_amendment(existing={existing_acc})"

    existing_fdate = _parse_ymd(existing_fdate_str)
    if incoming_filing_date is None:
        return False, f"no_incoming_filing_date_ambiguous(existing={existing_acc})"
    if existing_fdate is None:
        return True, f"existing_has_no_filing_date(existing={existing_acc})"
    if incoming_filing_date > existing_fdate:
        return True, f"incoming_newer({incoming_filing_date}>{existing_fdate},existing={existing_acc})"
    if incoming_filing_date < existing_fdate:
        return False, f"existing_newer({existing_fdate}>={incoming_filing_date},existing={existing_acc})"
    return True, f"tie_filing_date_prefer_incoming(existing={existing_acc})"


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

    # Strategy 1: Workiva double-number format: (N) label (N) value.
    # Carvana field numbers stay under ~200; any "(N)" with a comma or >200
    # value is a parenthesised dollar amount (e.g. "(3,277)" or "(525)"), not
    # a field marker. Use a conservative upper bound to avoid stopping the
    # value capture inside a negative amount.
    #
    # Additional guard: a genuine Workiva field pair has the TWO "(N)" tokens
    # within ~400 chars of each other (label length is small). Reject pairs
    # that span a huge distance — those are almost always a parenthesised
    # value that happens to collide with a later same-numbered marker
    # (e.g. "(93) ... (93) (138) (94) ... (138) <intrest rate table>").
    pattern1 = re.compile(r'\((\d+)\)\s*(.{0,400}?)\s*\(\1\)\s+(.*?)(?=\((?:[1-9]\d?|1\d{2}|200)\)|\Z)', re.DOTALL)
    for match in pattern1.finditer(text):
        field_num = int(match.group(1))
        label = match.group(2).strip()
        value_str = match.group(3).strip()
        fields[field_num] = {"label": label, "raw": value_str}

    # Genuine Workiva certs produce 100+ Strategy-1 hits. Donnelley certs have
    # formulas like "{sum of (17,23,29,35,41,47,53)}" and "{(14)*0.5%}" that
    # cause spurious Strategy-1 matches (a single bogus field swallows huge
    # amounts of surrounding text). Require a solid minimum before trusting
    # Strategy 1 and skipping Strategy 2.
    if len(fields) >= 20:
        return fields

    # Reset — any Strategy-1 hits in Donnelley text are noise
    fields = {}

    # Strategy 2: Donnelley single-number format: label (N) value
    # Each match captures everything after "(N)" up to the next "(M)" — which
    # contains the value followed by the next field's label.
    # Restrict the lookahead to realistic field numbers (1-200) so a
    # parenthesised negative value does not truncate the capture.
    pattern2 = re.compile(r'(?:^|(?<=\s))\((\d+)\)\s+(.*?)(?=\((?:[1-9]\d?|1\d{2}|200)\)|\Z)', re.DOTALL)
    ordered = []
    for match in pattern2.finditer(text):
        field_num = int(match.group(1))
        value_str = match.group(2).strip()
        ordered.append((field_num, value_str))

    # Post-pass: each raw is "<value tokens> <next-field label text>".
    # Split off the leading numeric tokens to recover the value and label.
    # The recovered "tail label" is the LABEL of the NEXT field, so back-fill.
    pending_label_for_next = ""
    for i, (fnum, raw) in enumerate(ordered):
        tokens = raw.split()
        val_tokens = []
        j = 0
        while j < len(tokens):
            tok = tokens[j]
            cleaned = tok.replace(",", "").replace("$", "").replace("(", "").replace(")", "").replace("%", "")
            # Numeric token (incl. negative, decimal, parenthesised, percent)
            if re.match(r'^-?\d[\d,.]*$', cleaned) and cleaned not in ("",):
                val_tokens.append(tok); j += 1
            elif tok in ("$", "%", "(", ")"):
                val_tokens.append(tok); j += 1
            elif re.match(r'^\d+-\d+$', cleaned):  # bucket like 31-60
                val_tokens.append(tok); j += 1
            else:
                break
        value_str = " ".join(val_tokens).strip()
        next_label = " ".join(tokens[j:]).strip()
        if fnum not in fields:
            fields[fnum] = {"label": pending_label_for_next, "raw": value_str}
        pending_label_for_next = next_label

    return fields


def _parse_numbered_value(raw: str, expect_count_and_amount: bool = False) -> dict:
    """Parse a raw value string into numbers.

    Some fields have both a count and amount: "5,401 20,294,118.53"
    Others have just one number: "139,999.54" or "4.48%"
    """
    result = {"value": None, "count": None, "pct": None}
    if not raw:
        return result

    # Check for percentage — but ONLY if the first numeric token is a
    # percentage. Many cert rows have values like "6,228,590 (d) Historical
    # Net Loss Data ... 26,662,743 (25,523) -0.10%" where the real value is
    # the leading dollar amount but a stray % appears later in unrelated
    # trailing label text. Matching the first number+% ensures we only treat
    # the field as a percentage when it genuinely is one.
    leading = re.match(r'\s*(-?[\d,.]+)\s*(%?)', raw)
    if leading and leading.group(2) == "%":
        result["pct"] = _clean_number(leading.group(1))
        return result

    # Extract number tokens from the BEGINNING of the value string.
    # Stop when we hit a word (letter character) that's not part of a number.
    # This avoids grabbing stray numbers from trailing label text like "60 days delinquent".
    tokens = raw.split()
    numbers = []
    pending_open_paren = False  # True after we've seen "(" starting a negative
    for token in tokens:
        # Skip range patterns like "31-60", "61-90"
        bare = token.replace(",", "").replace("$", "").replace("(", "").replace(")", "")
        if re.match(r'^\d+-\d+$', bare):
            continue
        # Skip lone $ prefix
        if token in ("$",):
            continue
        # Handle parenthesis-wrapped negatives: "(66,729 )" splits into
        # "(66,729" and ")". Also "(66,729)" as one token. Normalise the
        # token, extract numeric, tag sign.
        # Open paren starts a potential negative
        if token == "(":
            pending_open_paren = True
            continue
        if token == ")":
            # close paren; don't break the run — keep scanning
            continue
        # Strip surrounding parens and leading $ from the token for numeric test
        stripped = token.strip("()").lstrip("$")
        if re.match(r'^-?[\d,]+\.?\d*$', stripped.replace(",", "")):
            tok_negative = (token.startswith("(") or pending_open_paren)
            # If the token itself was "(NNN)" or "(NNN", or preceded by "(", treat as negative
            if tok_negative:
                numbers.append("-" + stripped)
            else:
                numbers.append(stripped)
            pending_open_paren = False
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

    # Extract aggregate note balance via regex (more reliable than field numbers which shift)
    # Pattern: "Aggregate Note Balance after all distributions ... NUMBER"
    agg_patterns = [
        r'[Aa]ggregate\s+[Nn]ote\s+[Bb]alance\s+after\s+all\s+distributions\s+(?:\{[^}]*\}\s+)?(?:\(\d+\)\s+)?([\d,]+\.?\d*)',
        r'[Aa]ggregate\s+[Nn]ote\s+[Bb]alance\s+after\s+all\s+distributions\s+([\d,]+\.?\d*)',
    ]
    for pattern in agg_patterns:
        m = re.search(pattern, all_text)
        if m and _clean_number(m.group(1)):
            val = _clean_number(m.group(1))
            if val > 0:
                best_result["aggregate_note_balance"] = val
                logger.debug(f"  aggregate_note_balance from regex: ${val:,.2f}")
                break

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
                continue  # Likely a note balance, not interest
            if cls_name not in note_interest_by_class:
                note_interest_by_class[cls_name] = val  # First match per class wins
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
    # Line numbers shift across cert vintages (prime 2020-P1 uses 91/95/98;
    # 2022+ vintages use 90/94/97; non-prime has a different numbering with
    # the same labels). Try the "usual" field numbers first, then fall back
    # to a label-based lookup that works across all variants.
    def _norm(s):
        # Collapse whitespace AND normalise unicode dashes / non-breaking
        # spaces to their ASCII equivalents so labels with u+2010 hyphens or
        # u+00a0 non-breaking spaces still match against ASCII search strings.
        if not s:
            return ""
        s = s.replace("\u00a0", " ")
        for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014"):
            s = s.replace(dash, "-")
        return re.sub(r'\s+', ' ', s).strip()

    def _by_label(label_substr):
        # Collapse whitespace in both sides so newlines/tabs inserted by HTML
        # layout do not break matching ("Receivables\nlosses" vs "Receivables losses").
        target = _norm(label_substr)
        for fnum, fdata in fields.items():
            lbl = _norm(fdata.get("label"))
            if target in lbl:
                return fdata["raw"]
        return None

    def _val(field_num):
        """Get parsed value from a numeric field, if present."""
        if field_num in fields:
            return _parse_numbered_value(fields[field_num]["raw"])["value"]
        return None

    def _pick(*candidates):
        """Return first non-None candidate (preserves 0 correctly)."""
        for c in candidates:
            if c is not None:
                return c
        return None

    def _label_val(label_substr):
        raw = _by_label(label_substr)
        if raw is None:
            return None
        return _parse_numbered_value(raw)["value"]

    if 8 in fields:
        v = _parse_numbered_value(fields[8]["raw"], expect_count_and_amount=True)
        data["gross_charged_off_amount"] = v["value"]
    # Prefer label-based lookup (Workiva), fall back to Donnelley fixed field
    # numbers, which are stable across Carvana 2020-P1 through mid-2023 certs.
    # Use _pick to preserve legitimate 0 values (vs Python's `or` which would
    # fall through to the next branch when the label-matched value is 0).
    data["gross_charged_off_amount"] = _pick(
        data.get("gross_charged_off_amount"),
        _label_val("Gross Charged-Off Receivables losses occurring in current Collection Period"),
        _val(90))
    data["cumulative_gross_losses"] = _pick(
        _label_val("Gross Charged-Off Receivables losses as of the last day of the current"),
        _val(91))
    data["liquidation_proceeds"] = _pick(
        _label_val("Gross Liquidation Proceeds occurring in the current Collection Period"),
        _val(93))
    data["cumulative_liquidation_proceeds"] = _pick(
        _label_val("Liquidation Proceeds as of the last day of the current"),
        _val(95))
    data["net_charged_off_amount"] = _pick(
        _label_val("Net Charged-Off Receivables losses occurring in current Collection Period"),
        _val(97))
    data["cumulative_net_losses"] = _pick(
        _label_val("Net Charged-Off Receivables losses as of the last day of the current"),
        _val(98))

    # --- Delinquency buckets ---
    # The bucket rows are numbered fields whose extracted "label" comes out
    # empty; the bucket tag ("31-60", "61-90", "91-120") lives at the start
    # of the raw string, e.g. "31-60 187 991,951.44". Look it up there.
    for bucket, (count_key, bal_key) in {
        "31-60": ("delinquent_31_60_count", "delinquent_31_60_balance"),
        "61-90": ("delinquent_61_90_count", "delinquent_61_90_balance"),
        "91-120": ("delinquent_91_120_count", "delinquent_91_120_balance"),
    }.items():
        raw = None
        for fnum, fdata in fields.items():
            lbl = (fdata.get("label") or "").strip()
            rv = (fdata.get("raw") or "").strip()
            if lbl.startswith(bucket) or rv.startswith(bucket):
                raw = rv
                # Drop the bucket tag so the count/amount parser sees clean values
                raw = re.sub(rf"^{re.escape(bucket)}\s+", "", raw)
                break
        if raw:
            v = _parse_numbered_value(raw, expect_count_and_amount=True)
            if v["count"] is not None: data[count_key] = int(v["count"])
            if v["value"] is not None: data[bal_key] = v["value"]
    # Total delinquencies row — also empty-label with "Total Delinquencies" in raw
    for fnum, fdata in fields.items():
        rv = (fdata.get("raw") or "").strip()
        lbl = (fdata.get("label") or "").strip()
        if rv.startswith("Total Delinquencies") or lbl.startswith("Total Delinquencies"):
            clean = re.sub(r"^Total Delinquencies\s+", "", rv)
            v = _parse_numbered_value(clean, expect_count_and_amount=True)
            if v["value"] is not None:
                data["total_delinquent_balance"] = v["value"]
            break
    if 103 in fields:
        data["delinquency_trigger_actual"] = _parse_numbered_value(fields[103]["raw"])["pct"]
        if data["delinquency_trigger_actual"]:
            data["delinquency_trigger_actual"] = data["delinquency_trigger_actual"] / 100.0
    if 104 in fields:
        data["delinquency_trigger_level"] = _parse_numbered_value(fields[104]["raw"])["pct"]
        if data["delinquency_trigger_level"]:
            data["delinquency_trigger_level"] = data["delinquency_trigger_level"] / 100.0

    # --- Note Balances (balance after monthly payment) ---
    # Actual cert layout per class (7 fields each, N has 5):
    #   A-1: 16(orig), 17(begin), 18(parity), 19(principal), 20(balance after), 21(pool factor)
    #   A-2: 22-27, A-3: 28-33, A-4: 34-39, B: 40-45, C: 46-51, D: 52-57
    #   N: 58(orig), 59(begin), 60(principal), 61(balance after), 62(pool factor)
    note_field_map = {
        20: "note_balance_a1", 26: "note_balance_a2", 32: "note_balance_a3",
        38: "note_balance_a4", 44: "note_balance_b", 50: "note_balance_c",
        56: "note_balance_d", 61: "note_balance_n",
    }
    for field_num, col_name in note_field_map.items():
        if field_num in fields:
            data[col_name] = _parse_numbered_value(fields[field_num]["raw"])["value"]

    # --- Note Rates (from "Calculation of Interest Distributable Amount" table, fields 136-143) ---
    # Each field contains: BOM Note Bal, Interest Carryover, Note Interest Rate, Days, Days Basis, Rate, Calculated Interest
    # We extract the rate (percentage) and the calculated interest (dollar amount)
    note_rate_fields = {
        136: ("A1", "note_rate_a1"), 137: ("A2", "note_rate_a2"),
        138: ("A3", "note_rate_a3"), 139: ("A4", "note_rate_a4"),
        140: ("B", "note_rate_b"), 141: ("C", "note_rate_c"),
        142: ("D", "note_rate_d"), 143: ("N", "note_rate_n"),
    }
    note_interest_total = 0.0
    for field_num, (cls_name, rate_col) in note_rate_fields.items():
        if field_num in fields:
            raw = fields[field_num]["raw"]
            # Extract percentage (note interest rate) — typically the first percentage in the field
            pcts = re.findall(r'([\d.]+)%', raw)
            if pcts:
                # The note coupon rate is usually the first percentage
                for pct_str in pcts:
                    pct = _clean_number(pct_str)
                    if pct and 0.01 < pct < 30:  # Reasonable annual rate range
                        data[rate_col] = pct / 100.0
                        break
            # Extract calculated interest (last dollar amount in the field)
            # Field format: "1 Class A-1 0.00 0 0.19% 28 7.78% 0.00"
            # The last number is the calculated interest for this class
            amounts = re.findall(r'([\d,]+\.?\d*)', raw)
            if amounts:
                # Last numeric value is the calculated interest
                calc_interest = _clean_number(amounts[-1])
                if calc_interest and calc_interest > 0:
                    note_interest_total += calc_interest

    # Also extract interest from the waterfall section via regex (more reliable)
    # Pattern: "Class X Interest Distributable Amount XXXX" in the waterfall
    # This is already handled by the regex parser in _parse_from_text()
    # but we compute it here too from the rate table as a cross-check
    if note_interest_total > 0:
        data["total_note_interest"] = note_interest_total
        logger.debug(f"  Note interest from rate table: ${note_interest_total:,.2f}")

    # Aggregate note balance: prefer sum of individual note balances (stable across vintages)
    # Field 76 is unreliable — it shifts between deal vintages (sometimes reserve amount)
    bal_sum = sum(data.get(col, 0) or 0 for col in
                  ["note_balance_a1", "note_balance_a2", "note_balance_a3", "note_balance_a4",
                   "note_balance_b", "note_balance_c", "note_balance_d", "note_balance_n"])
    if bal_sum > 0:
        data["aggregate_note_balance"] = bal_sum
    elif 76 in fields:
        # Fallback to field 76 only if individual balances unavailable
        data["aggregate_note_balance"] = _parse_numbered_value(fields[76]["raw"])["value"]

    # --- Overcollateralization & Reserve ---
    if 63 in fields:
        data["overcollateralization_amount"] = _parse_numbered_value(fields[63]["raw"])["value"]

    # Reserve account: field numbers for "Ending Reserve Account Balance" shift
    # across vintages (field 78 on some Workiva, field 80 on 2022-P1 Donnelley,
    # field 36 on 2021-N* non-prime). Prefer label-based lookup — _by_label
    # returns the FIRST match in insertion order, and the pool-level field
    # always appears before the Class N field, so "Ending Reserve Account
    # Balance" matches the pool reserve (never the "Ending Class N Reserve
    # Account Balance" section). Prior code hard-coded field 78 first AND then
    # overwrote with field 81 ("Specified Class N Reserve Account Amount"),
    # which: (a) read 0.00 on 2022-P1 (field 78 there is "Amount withdrawn"),
    # and (b) clobbered the pool reserve with the Class N threshold.
    end_raw = _by_label("Ending Reserve Account Balance")
    if end_raw is not None:
        data["reserve_account_balance"] = _parse_numbered_value(end_raw)["value"]
    elif 78 in fields:
        # Final fallback: bare field 78 (old Workiva layouts where the label
        # parser couldn't recover a clean label)
        data["reserve_account_balance"] = _parse_numbered_value(fields[78]["raw"])["value"]

    # Specified reserve: similar logic — prefer label, fall back to field 77
    spec_raw = _by_label("Specified Reserve Amount") or _by_label("Specified Reserve Account Amount")
    if spec_raw is not None:
        data["specified_reserve_amount"] = _parse_numbered_value(spec_raw)["value"]
    elif 77 in fields:
        data["specified_reserve_amount"] = _parse_numbered_value(fields[77]["raw"])["value"]
    if data.get("overcollateralization_amount") is None:
        oc_raw = _by_label("Overcollateralization in Dollars")
        if oc_raw:
            data["overcollateralization_amount"] = _parse_numbered_value(oc_raw)["value"]

    # --- Pool Statistics (fields 105-112) ---
    def _last_pct_from_raw(raw):
        nums = re.findall(r'[\d.]+%', raw or "")
        if nums:
            pct = _clean_number(nums[-1].replace("%", ""))
            return pct / 100.0 if pct else None
        return None
    def _last_num_from_raw(raw):
        nums = re.findall(r'[\d,]+\.?\d*', raw or "")
        if nums:
            return _clean_number(nums[-1])
        return None

    # Label-based extraction is most reliable — field numbers shift across
    # vintages (prime 2020-P1 used 105/106/107/108 for APR/term/orig/balance,
    # but Workiva 2024-P2 shifted them to 104/105/106/107, and non-prime certs
    # use a completely different scheme). Use labels first, fallback to field
    # numbers if labels miss.
    raw = _by_label("Weighted Average APR of the Receivables")
    if raw:
        data["weighted_avg_apr"] = _last_pct_from_raw(raw)
    elif 105 in fields:
        data["weighted_avg_apr"] = _last_pct_from_raw(fields[105]["raw"])

    raw = _by_label("Weighted Average Remaining Term of the Receivables")
    if raw:
        data["weighted_avg_remaining_term"] = _last_num_from_raw(raw)
    elif 106 in fields:
        data["weighted_avg_remaining_term"] = _last_num_from_raw(fields[106]["raw"])

    raw = _by_label("Weighted Average Original Term of the Receivables")
    if raw:
        data["weighted_avg_original_term"] = _last_num_from_raw(raw)
    elif 107 in fields:
        data["weighted_avg_original_term"] = _last_num_from_raw(fields[107]["raw"])

    # "Average Principal Balance" also appears inside the "Historical Net
    # Loss Data" header label (field 99 on Donnelley), so prefer the full
    # Receivables-qualified label, then a label that is EXACTLY "Average
    # Principal Balance" (ignoring surrounding whitespace).
    def _by_exact_label(target):
        tgt = _norm(target)
        for fnum, fdata in fields.items():
            lbl = _norm(fdata.get("label"))
            if lbl == tgt:
                return fdata["raw"]
        return None

    raw = (_by_label("Average Principal Balance of the Receivables")
           or _by_exact_label("Average Principal Balance"))
    if raw:
        data["avg_principal_balance"] = _last_num_from_raw(raw)
    elif 108 in fields:
        data["avg_principal_balance"] = _last_num_from_raw(fields[108]["raw"])

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
    """Parse servicer certificate HTML and store pool performance data.

    Looks up filing_type + filing_date from `filings` (keyed by accession) so
    callers don't change. Applies a stale-header override to distribution_date
    and resolves PK collisions explicitly (amendment / recency rules) instead
    of silently INSERT OR REPLACE-ing a previous period's row.
    """
    from carvana_abs.config import DB_PATH

    data = parse_servicer_certificate(html_content)
    if not data or not data.get("distribution_date"):
        logger.warning(f"Could not parse servicer certificate for {accession_number}")
        return False

    conn = get_connection(db_path or DB_PATH)
    cursor = conn.cursor()

    try:
        # Pull filing metadata for collision resolution + stale-header guard.
        meta = cursor.execute(
            "SELECT filing_type, filing_date FROM filings WHERE accession_number = ?",
            (accession_number,),
        ).fetchone()
        filing_type = meta[0] if meta else None
        filing_date = _parse_ymd(meta[1] if meta else None)

        stale, delta_days = _is_stale_header(data, filing_date, filing_type)
        if stale:
            # Stale header = cert re-reports the prior period's data under the
            # prior period's 'Distribution Date' literal. Inserting it would
            # either (a) clobber the real prior-period row on PK collision, or
            # (b) create a duplicate at a fabricated key. Neither is useful:
            # any authoritative data for THIS period lives on a subsequent /A.
            # Skip the write AND explicitly mark ingested_pool=0 so the
            # orphan-detection invariant ("ingested_pool=1 -> PP row exists")
            # stays clean.
            _audit(
                f"STALE_HEADER_SKIP deal={deal} accession={accession_number} "
                f"filing_date={filing_date.isoformat() if filing_date else 'NA'} "
                f"extracted_dist={data.get('distribution_date')} "
                f"delta_days={delta_days}"
            )
            cursor.execute(
                "UPDATE filings SET ingested_pool=0 WHERE accession_number=?",
                (accession_number,),
            )
            conn.commit()
            return True

        dist = data["distribution_date"]

        should_write, reason = _resolve_collision(
            conn, deal, dist, accession_number, filing_type, filing_date
        )
        if not should_write:
            # Filing's period is already covered by a higher-precedence row
            # (amendment wins, or newer plain filing wins). Keep ingested_pool=0
            # to preserve the invariant "ingested_pool=1 -> PP row exists".
            _audit(
                f"COLLISION_REJECT deal={deal} dist={dist} "
                f"incoming={accession_number} type={filing_type} reason={reason}"
            )
            cursor.execute(
                "UPDATE filings SET ingested_pool=0 WHERE accession_number=?",
                (accession_number,),
            )
            conn.commit()
            return True

        _audit(
            f"COLLISION_WRITE deal={deal} dist={dist} "
            f"incoming={accession_number} type={filing_type} reason={reason}"
        )

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
