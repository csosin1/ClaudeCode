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
import re
import logging
import sqlite3
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

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

    data["beginning_pool_balance"] = _grab_amount(text, r"1\.\s+Pool Balance on the close of the last day of the preceding")
    data["ending_pool_balance"]    = _grab_amount(text, r"5\.\s+Pool Balance on the close of the last day of the related")
    cnt = _grab_after(text, r"6\.\s+Total number of Receivables outstanding[^\n]*?", r"[\d,]+")
    if cnt: data["ending_pool_count"] = int(_clean_number(cnt))
    data["initial_pool_balance"] = _grab_amount(text, r"7\.\s+Initial Pool Balance")

    # Note balance — each row has Beginning $ End $; we want the End column.
    # Pattern allows arbitrary chars (e.g. "(sum a - g)") between the label
    # and the first $ amount.
    def _note_end(label):
        m = re.search(rf"{label}[^\n]*?\$\s*([\d,]+(?:\.\d+)?)\s+\$\s*([\d,]+(?:\.\d+)?)", text)
        return _clean_number(m.group(2)) if m else None
    data["note_balance_a1"] = _note_end(r"a\.\s+Class A-1 Note Balance")
    data["note_balance_a2"] = _note_end(r"b\.\s+Class A-2 Note Balance")
    data["note_balance_a3"] = _note_end(r"c\.\s+Class A-3 Note Balance")
    data["note_balance_a4"] = _note_end(r"d\.\s+Class A-4 Note Balance")
    data["note_balance_b"]  = _note_end(r"e\.\s+Class B Note Balance")
    data["note_balance_c"]  = _note_end(r"f\.\s+Class C Note Balance")
    data["note_balance_d"]  = _note_end(r"g\.\s+Class D Note Balance")
    data["aggregate_note_balance"] = _note_end(r"h\.\s+Note Balance")

    data["overcollateralization_amount"] = _grab_amount(text, r"11\.\s+Current overcollateralization amount")
    data["weighted_avg_apr"] = _grab_percent(text, r"12\.\s+Weighted Average Coupon")
    raw = _grab_after(text, r"13\.\s+Weighted Average Original Term[^\n]*?", r"[\d.]+")
    data["weighted_avg_original_term"] = _clean_number(raw)
    raw = _grab_after(text, r"14\.\s+Weighted Average Remaining Term[^\n]*?", r"[\d.]+")
    data["weighted_avg_remaining_term"] = _clean_number(raw)

    fc_coll = _grab_amount(text, r"a\.\s+Collections allocable to Finance Charge")
    fc_liq  = _grab_amount(text, r"b\.\s+Liquidation Proceeds allocable to Finance Charge")
    pr_coll = _grab_amount(text, r"a\.\s+Collections allocable to Principal")
    pr_liq  = _grab_amount(text, r"b\.\s+Liquidation Proceeds allocable to Principal")
    data["interest_collections"] = fc_coll
    data["principal_collections"] = pr_coll
    if fc_liq is not None or pr_liq is not None:
        data["liquidation_proceeds"] = (fc_liq or 0) + (pr_liq or 0)

    data["specified_reserve_amount"] = _grab_amount(text, r"47\.\s+Required Reserve Account Amount")
    data["reserve_account_balance"]  = _grab_amount(text, r"55\.\s+Ending Balance")
    data["residual_cash"] = _grab_amount(text, r"e\.\s+Excess Collections")
    data["regular_pda"]   = _grab_amount(text, r"37\.\s+Regular Principal Distributable Amount")
    data["actual_servicing_fee"] = _grab_amount(text, r"24\.\s+Servicing Fee[^\n]*?c\.\s+Amount Paid")
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

    for cnt_key, bal_key, pat in [
        ("delinquent_31_60_count",   "delinquent_31_60_balance",   r"a\.\s+31 to 60 days past due"),
        ("delinquent_61_90_count",   "delinquent_61_90_balance",   r"b\.\s+61 to 90 days past due"),
        ("delinquent_91_120_count",  "delinquent_91_120_balance",  r"c\.\s+91 to 120 days past due"),
        ("delinquent_121_plus_count", "delinquent_121_plus_balance", r"d\.\s+121 or more days past due"),
    ]:
        c, b = _grab_count_and_amount(text, pat)
        if c is not None: data[cnt_key] = c
        if b is not None: data[bal_key] = b
    _, total_dq = _grab_count_and_amount(text, r"e\.\s+Total Past Due")
    if total_dq is not None:
        data["total_delinquent_balance"] = total_dq
    data["delinquency_trigger_actual"] = _grab_percent(text, r"f\.\s+Delinquent Loans as a percentage")

    co_count, co_amt = _grab_count_and_amount(text, r"73\.\s+Defaulted Receivables")
    if co_amt is not None: data["gross_charged_off_amount"] = co_amt
    rec_count, rec_amt = _grab_count_and_amount(text, r"74\.\s+Recoveries")
    data["net_charged_off_amount"] = _grab_amount(text, r"75\.\s+Net Losses")
    if rec_amt is not None and "recoveries" not in data:
        data["recoveries"] = rec_amt

    _, data["cumulative_gross_losses"] = _grab_count_and_amount(text, r"77\.\s+Defaulted Receivables")
    _, data["cumulative_liquidation_proceeds"] = _grab_count_and_amount(text, r"78\.\s+Recoveries")
    data["cumulative_net_losses"] = _grab_amount(text, r"79\.\s+Cumulative Net Losses")

    data["extensions_balance"] = _grab_amount(text, r"82\.\s+Principal Balance of Receivables extended")
    return data


def store_pool_data(html_content: str, accession_number: str,
                    deal: str, db_path: str) -> bool:
    """Parse + upsert into pool_performance. Mirror of the Carvana version."""
    data = parse_servicer_certificate(html_content)
    if not data.get("distribution_date"):
        return False
    conn = sqlite3.connect(db_path)
    try:
        cols = ["deal", "distribution_date", "accession_number"]
        vals = [deal, data["distribution_date"], accession_number]
        for k, v in data.items():
            if k == "distribution_date" or v is None: continue
            cols.append(k); vals.append(v)
        placeholders = ",".join(["?"] * len(cols))
        conn.execute(
            f"INSERT OR REPLACE INTO pool_performance ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        conn.execute("UPDATE filings SET ingested_pool=1 WHERE accession_number=?",
                     (accession_number,))
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"DB error storing {accession_number}: {e}")
        return False
    finally:
        conn.close()
