"""Parser for CARMX (CarMax Auto Owner Trust) servicer-cert HTML.

CARMX certificates use a different format from Carvana's image-based
filings — they're Workiva-generated HTML with a clean line-numbered
table ("Ln NN.X" labels). Every value the dashboard needs is in plain
text:

    Ln 1   Beginning Pool Balance ($)
    Ln 5   Ending Pool Balance ($)
    Ln 6   Receivables outstanding (count)
    Ln 7   Initial Pool Balance ($) — cutoff balance
    Ln 8a-h  Note balances per class (Beg / End)
    Ln 11  Overcollateralization
    Ln 12  Weighted Average Coupon (%)
    Ln 13/14  Weighted Avg Original/Remaining Term
    Ln 15a/b  Finance Charge collections / liquidation
    Ln 16a/b  Principal collections / liquidation
    Ln 24c Servicing Fee paid
    Ln 27d/h/l/p, 29d, 31d, 33d  per-class total interest
    Ln 37  Regular Principal Distributable Amount
    Ln 41e Total Deposits to Collection Account
    Ln 42e Excess Collections (residual cash)
    Ln 47  Required Reserve Account Amount
    Ln 55  Reserve Account Ending Balance
    Ln 71a-d  31-60 / 61-90 / 91-120 / 121+ DQ buckets (count + $)
    Ln 71e Total Past Due
    Ln 71f Delinquency rate %
    Ln 73  Period gross charge-offs (count + $)
    Ln 74  Period recoveries (count + $)
    Ln 75  Period net loss
    Ln 77  Cumulative gross charge-offs
    Ln 78  Cumulative recoveries
    Ln 79  Cumulative net losses
    Ln 80  Cum loss / initial pool %
    Ln 82  Extensions in period
"""

from __future__ import annotations
import os
import re
import logging
import sqlite3
from datetime import datetime, date
from typing import Optional, Tuple
from bs4 import BeautifulSoup

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
    """Parse an 'M/D/YYYY' distribution-date string."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%m/%d/%Y").date()
    except (ValueError, TypeError):
        return None


def _parse_ymd(s: Optional[str]) -> Optional[date]:
    """Parse a 'YYYY-MM-DD' filing_date string."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None

# A "real" dollar amount in CARMX certs is always preceded by "$" — values
# inside formula parentheticals like "(Ln 77 - Ln 78)" are bare numbers and
# must NOT be matched, so the leading $ is required.
_AMT = r"\$\s*\(?\s*-?[\d,]+(?:\.\d+)?\s*\)?"
_PCT = r"-?[\d,]+(?:\.\d+)?\s*%"


def _normalize(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    txt = soup.get_text(separator=" ", strip=True)
    txt = re.sub(r"&nbsp;|&#160;", " ", txt)
    return re.sub(r"\s+", " ", txt)


def _clean_number(s: Optional[str]) -> Optional[float]:
    if s is None: return None
    s = s.strip().replace(",", "").replace("$", "").replace("%", "")
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def _grab_after(text: str, after_pat: str, value_pat: str) -> Optional[str]:
    m = re.search(after_pat + r"[^\n]*?(" + value_pat + ")", text)
    return m.group(1) if m else None


def _grab_amount(text: str, label: str) -> Optional[float]:
    return _clean_number(_grab_after(text, label, _AMT))


def _grab_percent(text: str, label: str) -> Optional[float]:
    raw = _grab_after(text, label, _PCT)
    if raw is None: return None
    v = _clean_number(raw)
    return v / 100.0 if v is not None else None


def _grab_count_and_amount(text: str, label: str) -> tuple[Optional[int], Optional[float]]:
    """For lines like 'a. 31 to 60 days past due 704 $ 6,271,227.97'."""
    m = re.search(label + r"[^\n]*?([\d,]+)\s+\$?\s*([\d,]+(?:\.\d+)?)", text)
    if not m: return None, None
    c = _clean_number(m.group(1))
    a = _clean_number(m.group(2))
    return (int(c) if c is not None else None), a


def parse_servicer_certificate(html: str) -> dict:
    """Parse a CARMX servicer cert into a dict matching the dashboard schema."""
    text = _normalize(html)
    data: dict = {}

    m = re.search(r"Distribution\s+Date\s+(\d{1,2}/\d{1,2}/\d{4})", text)
    if m:
        data["distribution_date"] = m.group(1)

    # Line numbers for opening balance table are stable across vintages,
    # but keep label-anchored with a flexible line number prefix for safety.
    # Some 2014-era certs render line numbers as "1 ." (space before period)
    # instead of "1.", so the prefix tolerates optional whitespace.
    data["beginning_pool_balance"] = _grab_amount(text, r"\d+\s*\.\s+Pool Balance on the close of the last day of the preceding")
    data["ending_pool_balance"]    = _grab_amount(text, r"\d+\s*\.\s+Pool Balance on the close of the last day of the related")
    cnt = _grab_after(text, r"\d+\s*\.\s+Total number of Receivables outstanding[^\n]*?", r"[\d,]+")
    if cnt: data["ending_pool_count"] = int(_clean_number(cnt))
    # Initial Pool Balance — usually "$ X", but some late-period certs drop
    # the "$".  Use a slightly looser pattern that picks up either.
    m_init = re.search(r"\d+\s*\.\s+Initial Pool Balance\s*\$?\s*([\d,]+(?:\.\d+)?)", text)
    if m_init:
        data["initial_pool_balance"] = _clean_number(m_init.group(1))

    # Note balance — each row has Beginning $ End $; we want the End column.
    # Letter prefixes shifted in 2021-3+ when A-2 was split into A-2a + A-2b
    # Floating (class count went from 7 to 8), moving the aggregate sum line
    # from "h." to "i." and pushing every class after A-2 down one letter.
    # Match by CLASS NAME, not by letter prefix.
    def _note_end(label):
        # Require a letter-prefix marker before the class name so we don't
        # accidentally pick up "Class A-1 Note Pool Factor" or other
        # non-balance rows that happen to mention the class.
        pat = rf"[a-z]\.\s+{label}[^\n]*?\$\s*([\d,]+(?:\.\d+)?)\s+\$\s*([\d,]+(?:\.\d+)?)"
        m = re.search(pat, text)
        return _clean_number(m.group(2)) if m else None

    # Class A-2 renders as either "Class A-2 Note Balance" (pre-split) or as
    # two separate rows "Class A-2a Note Balance" + "Class A-2b Floating Rate
    # Note Balance" (2021-3 onward). When split, sum the two halves into the
    # single note_balance_a2 column to keep the schema stable.
    a2_single = _note_end(r"Class A-2 Note Balance")
    if a2_single is not None:
        data["note_balance_a2"] = a2_single
    else:
        a2a = _note_end(r"Class A-2a Note Balance")
        a2b = _note_end(r"Class A-2b Floating Rate Note Balance")
        if a2a is not None or a2b is not None:
            data["note_balance_a2"] = (a2a or 0) + (a2b or 0)

    data["note_balance_a1"] = _note_end(r"Class A-1 Note Balance")
    data["note_balance_a3"] = _note_end(r"Class A-3 Note Balance")
    data["note_balance_a4"] = _note_end(r"Class A-4 Note Balance")
    data["note_balance_b"]  = _note_end(r"Class B Note Balance")
    data["note_balance_c"]  = _note_end(r"Class C Note Balance")
    data["note_balance_d"]  = _note_end(r"Class D Note Balance")

    # Aggregate: explicit "Note Balance (sum a - g/h)" row. Letter prefix
    # differs by vintage (h. pre-split, i. post-split) so match on the label
    # body, not the prefix. Falls back to class-sum if the aggregate row is
    # missing or malformed.
    m_agg = re.search(
        r"[a-z]\.\s+Note Balance\s*\(sum a\s*-\s*[a-z]\)[^\n]*?\$\s*[\d,]+(?:\.\d+)?\s+\$\s*([\d,]+(?:\.\d+)?)",
        text,
    )
    if m_agg:
        data["aggregate_note_balance"] = _clean_number(m_agg.group(1))
    else:
        parts = [data.get(k) for k in ("note_balance_a1", "note_balance_a2",
                                       "note_balance_a3", "note_balance_a4",
                                       "note_balance_b", "note_balance_c",
                                       "note_balance_d")]
        if any(p is not None for p in parts):
            data["aggregate_note_balance"] = sum(p or 0 for p in parts)

    data["overcollateralization_amount"] = _grab_amount(text, r"\d+\s*\.\s+Current overcollateralization amount")
    data["weighted_avg_apr"] = _grab_percent(text, r"\d+\s*\.\s+Weighted Average Coupon")
    raw = _grab_after(text, r"\d+\s*\.\s+Weighted Average Original Term[^\n]*?", r"[\d.]+")
    data["weighted_avg_original_term"] = _clean_number(raw)
    raw = _grab_after(text, r"\d+\s*\.\s+Weighted Average Remaining Term[^\n]*?", r"[\d.]+")
    data["weighted_avg_remaining_term"] = _clean_number(raw)

    fc_coll = _grab_amount(text, r"a\.\s+Collections allocable to Finance Charge")
    fc_liq  = _grab_amount(text, r"b\.\s+Liquidation Proceeds allocable to Finance Charge")
    pr_coll = _grab_amount(text, r"a\.\s+Collections allocable to Principal")
    pr_liq  = _grab_amount(text, r"b\.\s+Liquidation Proceeds allocable to Principal")
    data["interest_collections"] = fc_coll
    data["principal_collections"] = pr_coll
    if fc_liq is not None or pr_liq is not None:
        data["liquidation_proceeds"] = (fc_liq or 0) + (pr_liq or 0)

    data["specified_reserve_amount"] = _grab_amount(text, r"\d+\s*\.\s+Required Reserve Account Amount")
    # Reserve Account Ending Balance: line number drifts by vintage
    #   2014 certs          -> "56. Ending Balance"
    #   2017-2020, non-split -> "55. Ending Balance"
    #   2021-3+ (A-2 split)  -> "57. Ending Balance"
    # "Ending Balance" is unique to the Reserve Account section in every
    # CARMX vintage sampled, so a number-agnostic anchor is safe.
    data["reserve_account_balance"]  = _grab_amount(text, r"\d+\s*\.\s+Ending Balance")
    data["residual_cash"] = _grab_amount(text, r"e\.\s+Excess Collections")
    data["regular_pda"]   = _grab_amount(text, r"37\s*\.\s+Regular Principal Distributable Amount")
    data["actual_servicing_fee"] = _grab_amount(text, r"24\s*\.\s+Servicing Fee[^\n]*?c\.\s+Amount Paid")
    data["total_deposited"] = _grab_amount(text, r"e\.\s+Total Deposits to Collection Account")

    total_int = 0.0; saw_any = False
    for label in [r"d\.\s+Total Class A-1 Note Interest",
                  r"h\.\s+Total Class A-2 Note Interest",
                  r"l\.\s+Total Class A-3 Note Interest",
                  r"p\.\s+Total Class A-4 Note Interest",
                  r"d\.\s+Total Class B Note Interest",
                  r"d\.\s+Total Class C Note Interest",
                  r"d\.\s+Total Class D Note Interest"]:
        v = _grab_amount(text, label)
        if v is not None:
            total_int += v; saw_any = True
    if saw_any:
        data["total_note_interest"] = total_int

    # Delinquency buckets.
    #   2016+ certs: 4 buckets — 31-60 / 61-90 / 91-120 / 121+ with "e. Total
    #   Past Due (sum a - d)" and "f. Delinquent Loans as a percentage".
    #   2014-2015 certs: 3 buckets — 31-60 / 61-90 / "91 or more" with
    #   "d. Total Past Due (sum a - c)"; no trigger %.
    # Match on the body of the label, not the letter prefix — old/new formats
    # use different letters for the total line and the 91+ bucket. The 91+
    # bucket maps to `delinquent_91_120_balance` for old-format deals (no
    # 121+ bucket exists to populate separately); this keeps one code path.
    for cnt_key, bal_key, pat in [
        ("delinquent_31_60_count",   "delinquent_31_60_balance",   r"[a-z]\.\s+31 to 60 days past due"),
        ("delinquent_61_90_count",   "delinquent_61_90_balance",   r"[a-z]\.\s+61 to 90 days past due"),
        ("delinquent_91_120_count",  "delinquent_91_120_balance",  r"[a-z]\.\s+91 (?:to 120|or more) days past due"),
        ("delinquent_121_plus_count", "delinquent_121_plus_balance", r"[a-z]\.\s+121 or more days past due"),
    ]:
        c, b = _grab_count_and_amount(text, pat)
        if c is not None: data[cnt_key] = c
        if b is not None: data[bal_key] = b
    _, total_dq = _grab_count_and_amount(text, r"[a-z]\.\s+Total Past Due")
    if total_dq is not None:
        data["total_delinquent_balance"] = total_dq
    data["delinquency_trigger_actual"] = _grab_percent(text, r"[a-z]\.\s+Delinquent Loans as a percentage")

    # Period loss / recovery / net.
    # 2017+ certs have two distinct lines for period vs cumulative, both
    # using identical labels — first occurrence is PERIOD, second is
    # CUMULATIVE.  The "(charge-offs)" / "(recoveries)" suffix
    # distinguishes them from line-4 "Defaulted Receivables" (period $
    # only, no count).  2014 certs lack the suffix and the cumulative
    # breakdowns entirely — only the consolidated "Cumulative Net Losses"
    # line exists.
    # Defaulted Receivables breakdown.
    # 2016+ certs have two "(charge-offs)" lines (period + cumulative);
    # 2014-2015 certs only have the line-4 period "Defaulted Receivables $ X"
    # with no count and no cumulative breakdown. Amount may be negative when
    # prior-period charge-offs are reversed (rare but valid).
    all_def = list(re.finditer(
        r"\d+\s*\.\s+Defaulted Receivables\s*\(charge-offs?\)\s+([\d,]+)\s+\$\s*(-?[\d,]+(?:\.\d+)?)", text))
    if all_def:
        data["gross_charged_off_amount"] = _clean_number(all_def[0].group(2))
        if len(all_def) > 1:
            data["cumulative_gross_losses"] = _clean_number(all_def[-1].group(2))
    else:
        # 2014-era fallback: line 4 has "Defaulted Receivables $ X" no count
        m4 = re.search(r"\d+\s*\.\s+Defaulted Receivables\s+\$\s*(-?[\d,]+(?:\.\d+)?)", text)
        if m4:
            data["gross_charged_off_amount"] = _clean_number(m4.group(1))

    # Recoveries label varies by vintage:
    #   "Liquidation Proceeds (recoveries)"  (some 2017-era certs)
    #   "Recoveries"                          (most 2017+ certs)
    # Both formats: <n>. <label> <count> $ <amount>
    # Amount MUST allow a leading "-" — monthly recoveries can be negative
    # when prior recoveries are reversed/clawed back. Without this the
    # period row silently fails to match and the cumulative row's value is
    # mis-stored under `recoveries` (see AUDIT_FINDINGS F-010).
    # 2014-2015 certs have no recoveries line at all — both columns stay NULL.
    all_rec = list(re.finditer(
        r"\d+\s*\.\s+(?:Liquidation Proceeds\s*\(recoveries\)|Recoveries)\s+([\d,]+)\s+\$\s*(-?[\d,]+(?:\.\d+)?)", text))
    if all_rec:
        if "recoveries" not in data:
            data["recoveries"] = _clean_number(all_rec[0].group(2))
        if len(all_rec) > 1:
            data["cumulative_liquidation_proceeds"] = _clean_number(all_rec[-1].group(2))

    # Period net loss.
    # 2016+ certs: "<n>. Net Losses (Ln <a> - Ln <b>) $ X" — can be negative.
    # 2014-2015 certs: "<n>. Net Losses with respect to preceding Collection
    # Period $ X" — never negative in practice (no recoveries line).
    m_net = re.search(
        r"\d+\s*\.\s+Net Losses"
        r"(?:\s+\(Ln[^)]*\)|\s+with respect to preceding Collection Period)?"
        r"\s+\$\s*(-?[\d,]+(?:\.\d+)?)",
        text,
    )
    if m_net:
        data["net_charged_off_amount"] = _clean_number(m_net.group(1))

    # Cumulative net loss
    m_cum = re.search(r"\d+\s*\.\s+Cumulative Net Losses[^\n]*?\$\s*([\d,]+(?:\.\d+)?)", text)
    if m_cum:
        data["cumulative_net_losses"] = _clean_number(m_cum.group(1))

    # Extensions
    m_ext = re.search(r"\d+\s*\.\s+Principal Balance of Receivables extended[^\n]*?\$\s*([\d,]+(?:\.\d+)?)", text)
    if m_ext:
        data["extensions_balance"] = _clean_number(m_ext.group(1))
    return data


def _is_stale_header(
    data: dict,
    filing_date: Optional[date],
    filing_type: Optional[str],
) -> Tuple[bool, int]:
    """Detect stale-header filings: issuer copied the prior period's
    'Distribution Date' literal into the current cert so the extracted
    distribution_date disagrees with filing_date by >30 days.

    Amendments (/A) are excluded: they're legitimately filed weeks or months
    after the period they restate.

    Returns (is_stale, delta_days).
    """
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
    conn: sqlite3.Connection,
    deal: str,
    distribution_date: str,
    incoming_accession: str,
    incoming_filing_type: Optional[str],
    incoming_filing_date: Optional[date],
) -> Tuple[bool, Optional[str]]:
    """Decide whether incoming filing should overwrite the existing row at
    (deal, distribution_date). Returns (should_write, reason).

    Precedence:
      1. If incoming filing_type ends with '/A' and existing is NOT '/A'
         -> accept (amendment wins).
      2. If existing is '/A' and incoming is NOT '/A' -> reject
         (don't clobber an amendment with a later-ingested original 10-D).
      3. Both '/A' or both plain -> later filing_date wins; tie -> incoming.
      4. No existing row -> accept.
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

    existing_acc, existing_type, existing_fdate_str = row
    if existing_acc == incoming_accession:
        # Re-ingest of the same filing — always allow (parser bug fixes etc.).
        return True, "same_accession_reingest"

    incoming_is_a = bool(incoming_filing_type and incoming_filing_type.endswith("/A"))
    existing_is_a = bool(existing_type and existing_type.endswith("/A"))

    if incoming_is_a and not existing_is_a:
        return True, f"amendment_overwrites_original(existing={existing_acc})"
    if existing_is_a and not incoming_is_a:
        return False, f"refuse_overwrite_amendment(existing={existing_acc})"

    # Same tier (both /A or both plain) — prefer later filing_date.
    existing_fdate = _parse_ymd(existing_fdate_str)
    if incoming_filing_date is None:
        return False, f"no_incoming_filing_date_ambiguous(existing={existing_acc})"
    if existing_fdate is None:
        return True, f"existing_has_no_filing_date(existing={existing_acc})"
    if incoming_filing_date > existing_fdate:
        return True, f"incoming_newer({incoming_filing_date}>{existing_fdate},existing={existing_acc})"
    if incoming_filing_date < existing_fdate:
        return False, f"existing_newer({existing_fdate}>={incoming_filing_date},existing={existing_acc})"
    # Equal filing_date — prefer incoming (idempotent re-runs get stable outcome).
    return True, f"tie_filing_date_prefer_incoming(existing={existing_acc})"


def store_pool_data(html_content: str, accession_number: str,
                    deal: str, db_path: str) -> bool:
    """Parse + upsert into pool_performance with collision-safe logic.

    Looks up filing_type + filing_date from `filings` (keyed by accession) so
    callers don't need to change. Applies a stale-header override on the
    extracted distribution_date, then resolves PK collisions explicitly
    instead of blindly INSERT OR REPLACE.
    """
    data = parse_servicer_certificate(html_content)
    if not data.get("distribution_date"):
        return False

    conn = sqlite3.connect(db_path)
    try:
        meta = conn.execute(
            "SELECT filing_type, filing_date FROM filings WHERE accession_number = ?",
            (accession_number,),
        ).fetchone()
        filing_type = meta[0] if meta else None
        filing_date = _parse_ymd(meta[1]) if meta else None

        stale, delta_days = _is_stale_header(data, filing_date, filing_type)
        if stale:
            # Stale header: cert re-reports the prior period's data under the
            # prior period's literal 'Distribution Date'. Skip the write and
            # keep ingested_pool=0 so the orphan-detection invariant stays
            # clean. Any authoritative data for THIS period arrives separately
            # on a /A amendment.
            _audit(
                f"STALE_HEADER_SKIP deal={deal} accession={accession_number} "
                f"filing_date={filing_date.isoformat() if filing_date else 'NA'} "
                f"extracted_dist={data.get('distribution_date')} "
                f"delta_days={delta_days}"
            )
            conn.execute(
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
            # Period is already covered by a higher-precedence row (amendment
            # wins, or newer plain filing wins). Keep ingested_pool=0 to
            # preserve the invariant "ingested_pool=1 -> PP row exists".
            _audit(
                f"COLLISION_REJECT deal={deal} dist={dist} "
                f"incoming={accession_number} type={filing_type} reason={reason}"
            )
            conn.execute(
                "UPDATE filings SET ingested_pool=0 WHERE accession_number=?",
                (accession_number,),
            )
            conn.commit()
            return True

        _audit(
            f"COLLISION_WRITE deal={deal} dist={dist} "
            f"incoming={accession_number} type={filing_type} reason={reason}"
        )

        cols = ["deal", "distribution_date", "accession_number"]
        vals = [deal, dist, accession_number]
        for k, v in data.items():
            if k == "distribution_date" or v is None:
                continue
            cols.append(k)
            vals.append(v)
        placeholders = ",".join(["?"] * len(cols))
        conn.execute(
            f"INSERT OR REPLACE INTO pool_performance ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        conn.execute(
            "UPDATE filings SET ingested_pool=1 WHERE accession_number=?",
            (accession_number,),
        )
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"DB error storing {accession_number}: {e}")
        return False
    finally:
        conn.close()
