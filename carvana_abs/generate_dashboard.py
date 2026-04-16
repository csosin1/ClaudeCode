#!/usr/bin/env python3
"""Generate static HTML dashboard using raw Plotly.js (no Python Plotly serialization)."""

import os, re, sys, sqlite3, json, logging
from datetime import datetime
from urllib.parse import urlparse
import pandas as pd

# Ensure the repository root is on sys.path so sibling packages (carmax_abs,
# carvana_abs) resolve when this file is invoked as a script.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db")
DASH_DB = os.path.join(DB_DIR, "dashboard.db")
FULL_DB = os.path.join(DB_DIR, "carvana_abs.db")
ACTIVE_DB = DASH_DB if os.path.exists(DASH_DB) else FULL_DB

# CarMax (CARMX) database paths. CarMax is Prime-only; when the dashboard DB
# doesn't exist yet (e.g. CI without the export step), we fall back to the raw
# ingestion DB. Both may be missing in a Carvana-only environment — every
# CarMax code path guards on `os.path.exists(CARMAX_DB)` before running.
CARMAX_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "carmax_abs", "db")
CARMAX_DASH_DB = os.path.join(CARMAX_DB_DIR, "dashboard.db")
CARMAX_FULL_DB = os.path.join(CARMAX_DB_DIR, "carmax_abs.db")
CARMAX_DB = (CARMAX_DASH_DB if os.path.exists(CARMAX_DASH_DB)
             else CARMAX_FULL_DB if os.path.exists(CARMAX_FULL_DB)
             else None)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_site")
os.makedirs(OUT_DIR, exist_ok=True)

# Deals to include in the dashboard — all deals with ingested data
DASHBOARD_DEALS = [
    "2020-P1",
    "2021-N1", "2021-N2", "2021-N3", "2021-N4", "2021-P1", "2021-P2",
    "2022-P1", "2022-P2", "2022-P3",
    "2024-P2", "2024-P3", "2024-P4",
    "2025-P2", "2025-P3", "2025-P4",
]
PRIME_DEALS = [d for d in DASHBOARD_DEALS if "-P" in d]
NONPRIME_DEALS = [d for d in DASHBOARD_DEALS if "-N" in d]

# CarMax deals. Loaded dynamically from the CARMX DB so new vintages picked up
# by the ingestion pipeline flow through without a code change. Falls back to
# the config registry if the DB isn't available (e.g. during unit tests).
def _load_carmax_deals():
    if not CARMAX_DB:
        return []
    try:
        conn = sqlite3.connect(CARMAX_DB)
        rows = conn.execute(
            "SELECT DISTINCT deal FROM pool_performance ORDER BY deal"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []

CARMAX_DEALS = _load_carmax_deals()
# CarMax sells sub-prime receivables rather than securitizing them, so every
# CARMX trust is Prime. Keep a CARMAX_PRIME_DEALS alias for consistency with
# the Carvana naming even though the filter is a no-op today.
CARMAX_PRIME_DEALS = list(CARMAX_DEALS)

COLORS = ["#1976D2","#D32F2F","#388E3C","#FF9800","#7B1FA2",
          "#00BCD4","#795548","#E91E63","#607D8B","#CDDC39","#FF5722","#3F51B5"]

# Carvana's chart colors already lean blue. For cross-issuer comparisons we
# need a second visually-distinct family. CarMax's brand palette is orange
# (#F47920) and yellow (#FFD200); we shade around those two hues so every
# CarMax deal on a chart is a CarMax-branded color.
CARMAX_COLORS = [
    "#F47920",  # CarMax brand orange
    "#FFD200",  # CarMax brand yellow
    "#E65100",  # deep orange
    "#F9A825",  # amber
    "#FF6F00",  # orange 900
    "#FBC02D",  # yellow 700
    "#BF360C",  # orange darkest
    "#FFB300",  # amber 600
    "#F57F17",  # amber 900
    "#FFEB3B",  # yellow
    "#D84315",  # deep orange 800
    "#FFCA28",  # amber 400
]
# Blue family for the Carvana leg of the cross-issuer tab — keeps every
# Carvana deal clearly distinguishable from every CarMax deal on one chart.
CARVANA_CROSS_COLORS = [
    "#0D47A1",  # blue 900
    "#1565C0",  # blue 800
    "#1976D2",  # blue 700 (the Carvana anchor color used elsewhere)
    "#1E88E5",  # blue 600
    "#2196F3",  # blue 500
    "#42A5F5",  # blue 400
    "#64B5F6",  # blue 300
    "#1A237E",  # indigo 900
    "#283593",  # indigo 800
    "#3949AB",  # indigo 600
    "#5C6BC0",  # indigo 400
    "#00838F",  # cyan/teal 700 (blue-adjacent)
    "#0097A7",  # cyan 700
    "#00ACC1",  # cyan 600
    "#26C6DA",  # cyan 400
    "#4FC3F7",  # light blue 300
]

_chart_id = 0


def q(sql, params=(), db=None):
    """Run a query and return a DataFrame.

    By default reads from the Carvana dashboard/raw DB (ACTIVE_DB). Pass
    db=CARMAX_DB to pull from the CarMax DB instead. All pre-existing call
    sites use the default and remain Carvana-scoped.
    """
    target = db if db is not None else ACTIVE_DB
    conn = sqlite3.connect(target)
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    for col in df.select_dtypes(include=["object"]).columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            pass
    return df


def nd(d):
    if not d: return d
    d = str(d).strip()
    for sep in ["-", "/"]:
        p = d.split(sep)
        if len(p) == 3 and len(p[0]) <= 2 and len(p[2]) == 4:
            return f"{p[2]}{sep}{p[0].zfill(2)}{sep}{p[1].zfill(2)}"
    return d


def fm(v):
    if v is None or (isinstance(v, float) and pd.isna(v)): return "-"
    if abs(v) >= 1e9: return f"${v/1e9:.1f}B"
    if abs(v) >= 1e6: return f"${v/1e6:.1f}M"
    if abs(v) >= 1e3: return f"${v/1e3:.0f}K"
    return f"${v:,.0f}"


def chart(traces, layout, height=350):
    """Generate a Plotly.js chart div using raw JSON data."""
    global _chart_id
    _chart_id += 1
    cid = f"c{_chart_id}"
    traces_json = json.dumps(traces)
    layout["margin"] = {"l": 70, "r": 15, "t": 40, "b": 50}
    layout["height"] = height
    layout["template"] = "plotly_white"
    layout["font"] = {"size": 11}
    layout.setdefault("xaxis", {})["tickangle"] = -45
    layout["xaxis"]["automargin"] = True
    layout.setdefault("yaxis", {})["automargin"] = True
    layout_json = json.dumps(layout)
    return f'<div id="{cid}" style="width:100%;height:{height}px;background:white;border-radius:8px;margin:8px 0;box-shadow:0 1px 3px rgba(0,0,0,.1)"></div>\n<script>Plotly.newPlot("{cid}",{traces_json},{layout_json},{{displayModeBar:false,responsive:true}});</script>\n'


def _restatement_overlay(x_list, y_list):
    """Build a monotone envelope + restatement-marker overlay for a cumulative
    loss series (audit finding #7). A restatement is any period where the raw
    cumulative value decreases from the prior period (servicers sometimes
    correct chargeoff/recovery allocations in a later cert).

    Returns (envelope_list, markers_x, markers_y). If no restatements are
    found, returns (None, [], []) so callers can omit the overlay entirely.
    """
    env = []
    markers_x, markers_y = [], []
    running_max = None
    restated = False
    for xv, yv in zip(x_list, y_list):
        if yv is None or (isinstance(yv, float) and pd.isna(yv)):
            env.append(running_max)
            continue
        yv_f = float(yv)
        if running_max is None:
            running_max = yv_f
        elif yv_f < running_max - 0.5:  # tolerance: sub-dollar noise is not a restatement
            markers_x.append(xv)
            markers_y.append(yv_f)
            restated = True
            # envelope stays at running_max
        else:
            running_max = max(running_max, yv_f)
        env.append(running_max)
    if not restated:
        return None, [], []
    return env, markers_x, markers_y


def table_html(df, cls=""):
    cls_attr = f' class="{cls}"' if cls else ""
    rows = "".join(f"<th>{c}</th>" for c in df.columns)
    header = f"<tr>{rows}</tr>"
    body = ""
    for _, row in df.iterrows():
        cells = "".join(f"<td>{row[c]}</td>" for c in df.columns)
        body += f"<tr>{cells}</tr>"
    return f'<div class="tbl"><table{cls_attr}><thead>{header}</thead><tbody>{body}</tbody></table></div>'


_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filing_cache")
_CERT_CACHE = {}


def _cert_totals(deal):
    """Parse authoritative cumulative totals from the deal's latest cached 10-D
    servicer certificate. Line-number references shift by vintage, so the regex
    keys off the label text, not the (NN) marker.

    Returns dict (may have None values) with:
      orig_pool_balance, cum_gross_losses, cum_liquidation_proceeds,
      cum_net_losses, ending_pool_balance.
    """
    if deal in _CERT_CACHE:
        return _CERT_CACHE[deal]
    result = {}
    row = q("SELECT servicer_cert_url FROM filings WHERE deal=? "
            "AND servicer_cert_url IS NOT NULL ORDER BY filing_date DESC LIMIT 1", (deal,))
    if row.empty:
        _CERT_CACHE[deal] = result
        return result
    url = row.iloc[0]["servicer_cert_url"]
    p = urlparse(url)
    path = os.path.join(_CACHE_DIR, p.path.strip("/").replace("/", "_"))
    if not os.path.exists(path):
        _CERT_CACHE[deal] = result
        return result
    try:
        with open(path, "r", errors="replace") as f:
            txt = f.read()
    except OSError:
        _CERT_CACHE[deal] = result
        return result
    body = re.sub(r"<[^>]+>", " ", re.sub(r"&nbsp;", " ", txt))
    body = re.sub(r"\s+", " ", body)

    def grab(label):
        pat = rf"{re.escape(label)}\s*\(?\s*\d+\s*\)?[^0-9]{{0,30}}([\d,]+(?:\.\d+)?)"
        m = re.search(pat, body)
        return float(m.group(1).replace(",", "")) if m else None

    result["orig_pool_balance"] = grab("Original Pool Balance as of Cutoff Date")
    result["cum_gross_losses"] = grab(
        "Aggregate Gross Charged-Off Receivables losses as of the last day of the current Collection Period")
    result["cum_liquidation_proceeds"] = grab(
        "Liquidation Proceeds as of the last day of the current Collection Period")
    result["cum_net_losses"] = (
        grab("aggregate amount of Net Charged-Off Receivables losses as of the last day of the current Collection Period")
        or grab("Aggregate amount of Net Charged-Off Receivables losses as of the last day of the current Collection Period"))
    m = re.search(r"Ending Pool Balance\s*\(?\s*\d+\s*\)?\s*[\d,]+\s+([\d,]+(?:\.\d+)?)", body)
    result["ending_pool_balance"] = float(m.group(1).replace(",", "")) if m else None
    _CERT_CACHE[deal] = result
    return result


def get_orig_bal(deal):
    """Return the deal's original cutoff pool balance.

    Priority:
      1. Servicer cert line item "Original Pool Balance as of Cutoff Date"
         — the authoritative source. Works for every deal whose cert we've
         cached, regardless of when we started ingesting 10-Ds for it.
      2. MAX(beginning_pool_balance) from pool_performance — for deals where
         cert parse fails. This equals cutoff only if our earliest 10-D was
         the first 10-D for the deal; understates for any deal where we
         started ingesting mid-life (e.g. 2021-P1: $399M vs true $415M).
      3. SUM(original_loan_amount) from the loan tape — last resort; over-
         states by a few % since it sums each loan's origination amount.
    """
    totals = _cert_totals(deal)
    if totals.get("orig_pool_balance"):
        return float(totals["orig_pool_balance"])
    fp = q("SELECT MAX(beginning_pool_balance) AS m FROM pool_performance "
           "WHERE deal=? AND beginning_pool_balance > 0", (deal,))
    if not fp.empty and fp.iloc[0]["m"] and fp.iloc[0]["m"] > 0:
        return float(fp.iloc[0]["m"])
    t = q("SELECT SUM(original_loan_amount) as s FROM loans WHERE deal=?", (deal,))
    if not t.empty and t.iloc[0]["s"] and t.iloc[0]["s"] > 0:
        return float(t.iloc[0]["s"])
    return 405_000_000


def _cert_dq_series(deal):
    """Return a list of (distribution_date, dq_31_120_balance, ending_pool_balance)
    parsed from every cached servicer cert for this deal.

    dq_31_120 = sum of 31-60 + 61-90 + 91-120 balances as reported in the cert's
    "Delinquency Data" block. The cert does NOT have a 120+ bucket (those loans
    are charged off by day 120-150 under Carvana's servicing policy), so this is
    a narrower definition than monthly_summary's 30+ DQ rate, which carries
    pre-charge-off loans in dq_120_plus_balance.
    """
    filings = q("SELECT servicer_cert_url, filing_date FROM filings "
                "WHERE deal=? AND servicer_cert_url IS NOT NULL", (deal,))
    if filings.empty:
        return []
    from datetime import datetime as _dt
    def _parse(s):
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
            try: return _dt.strptime(str(s).strip()[:10], fmt)
            except (ValueError, TypeError): pass
        return None
    points = []
    for _, row in filings.iterrows():
        url = row["servicer_cert_url"]
        p = urlparse(url)
        path = os.path.join(_CACHE_DIR, p.path.strip("/").replace("/", "_"))
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", errors="replace") as f:
                txt = f.read()
        except OSError:
            continue
        body = re.sub(r"<[^>]+>", " ", re.sub(r"&nbsp;", " ", txt))
        body = re.sub(r"\s+", " ", body)

        # Delinquency rows look like: "31-60 187 991,951.44"  (bucket, count, balance)
        # The count can be comma-formatted once it exceeds 999 (e.g. "1,482"), so
        # use [\d,]+ for count, not \d+.
        buckets = {}
        for m in re.finditer(r"(31-60|61-90|91-120)\s+[\d,]+\s+([\d,]+\.\d+)", body):
            buckets[m.group(1)] = float(m.group(2).replace(",", ""))
        if len(buckets) < 3:
            continue
        dq_total = buckets["31-60"] + buckets["61-90"] + buckets["91-120"]

        # Ending pool balance from same cert
        m = re.search(r"Ending Pool Balance\s*\(?\s*\d+\s*\)?\s*[\d,]+\s+([\d,]+(?:\.\d+)?)", body)
        if not m:
            continue
        epb = float(m.group(1).replace(",", ""))

        # Distribution date
        m = re.search(r"Distribution Date[:\s]+(\d{1,2}/\d{1,2}/\d{4})", body)
        if not m:
            continue
        dt = _parse(m.group(1))
        if dt is None:
            continue
        points.append((dt, dq_total, epb))
    # Dedupe by date
    by_date = {}
    for dt, dq, epb in points:
        by_date[dt] = (dq, epb)
    return [(dt, dq, epb) for dt, (dq, epb) in sorted(by_date.items())]


def _cum_net_loss_series(deal):
    """Return a list of (distribution_date, cum_net_loss_dollars) from every
    cached servicer cert for this deal, sorted chronologically. Used for the
    Cumulative Net Loss by Deal Age chart so the series reflects cert-
    authoritative totals rather than monthly_summary flow sums (which
    undercount deals with gaps in ABS-EE ingestion).
    """
    filings = q("SELECT servicer_cert_url, filing_date, accession_number FROM filings "
                "WHERE deal=? AND servicer_cert_url IS NOT NULL", (deal,))
    if filings.empty:
        return []
    from datetime import datetime as _dt
    def _parse(s):
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
            try: return _dt.strptime(str(s).strip()[:10], fmt)
            except (ValueError, TypeError): pass
        return None
    points = []
    for _, row in filings.iterrows():
        url = row["servicer_cert_url"]
        p = urlparse(url)
        path = os.path.join(_CACHE_DIR, p.path.strip("/").replace("/", "_"))
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", errors="replace") as f:
                txt = f.read()
        except OSError:
            continue
        body = re.sub(r"<[^>]+>", " ", re.sub(r"&nbsp;", " ", txt))
        body = re.sub(r"\s+", " ", body)

        def _grab(label):
            pat = rf"{re.escape(label)}\s*\(?\s*\d+\s*\)?[^0-9]{{0,30}}([\d,]+(?:\.\d+)?)"
            m = re.search(pat, body)
            return float(m.group(1).replace(",", "")) if m else None

        cn = (_grab("aggregate amount of Net Charged-Off Receivables losses as of the last day of the current Collection Period")
              or _grab("Aggregate amount of Net Charged-Off Receivables losses as of the last day of the current Collection Period"))
        if cn is None:
            g = _grab("Aggregate Gross Charged-Off Receivables losses as of the last day of the current Collection Period")
            l = _grab("Liquidation Proceeds as of the last day of the current Collection Period")
            if g is not None and l is not None:
                cn = g - l
        if cn is None:
            continue
        # Extract the distribution date from the cert to anchor chronology
        m = re.search(r"Distribution Date[:\s]+(\d{1,2}/\d{1,2}/\d{4})", body)
        if not m:
            # Fall back to filing_date
            dt = _parse(row["filing_date"])
        else:
            dt = _parse(m.group(1))
        if dt is None:
            continue
        points.append((dt, cn))
    # Chronological, dedupe on date (keep max if multiple)
    by_date = {}
    for dt, cn in points:
        by_date[dt] = max(by_date.get(dt, cn), cn)
    return sorted(by_date.items())


def get_cum_net_loss_rate(deal, orig_bal):
    """Return the deal's cumulative net-loss rate as of the latest servicer cert.

    Prefer the cert's "(98) aggregate amount of Net Charged-Off Receivables
    losses as of the last day of the current Collection Period" — or, if that
    specific line is missing from the cert, gross − liquidation proceeds from
    the same cert. Fall back to summing monthly_summary flow data only when
    no cert values can be parsed; that fallback is known to undercount any
    deal with gaps in our ABS-EE ingestion (2020-P1, 2021-P1, 2021-P2 and a
    handful of others are missing 1–4 early months).
    """
    if not orig_bal or orig_bal <= 0:
        return None
    t = _cert_totals(deal)
    cn = t.get("cum_net_losses")
    if cn is None:
        cg = t.get("cum_gross_losses")
        cl = t.get("cum_liquidation_proceeds")
        if cg is not None and cl is not None:
            cn = cg - cl
    if cn is not None:
        return cn / orig_bal
    # Last-resort fallback: monthly_summary sums
    loss = q("SELECT SUM(period_chargeoffs) as co, SUM(period_recoveries) as rec "
             "FROM monthly_summary WHERE deal=?", (deal,))
    if loss.empty:
        return None
    net = (loss.iloc[0]["co"] or 0) - (loss.iloc[0]["rec"] or 0)
    return net / orig_bal


# ────────────────────────────────────────────────────────────────────────────
# CarMax (CARMX) helpers
#
# CarMax pool_performance has the same schema as Carvana's, but distribution
# dates are stored in M/D/YYYY string form — which does not string-sort in
# chronological order. All CarMax helpers normalize via `nd()` (→ YYYY/MM/DD)
# before sorting. Loan-level tables (loans, monthly_summary, loan_loss_summary)
# exist in the schema but are empty today; anything that depends on them
# degrades to a "loan-level data not yet ingested" message.
# ────────────────────────────────────────────────────────────────────────────

def carmax_available():
    """True if the CarMax dashboard DB exists and has pool data."""
    return CARMAX_DB is not None and bool(CARMAX_DEALS)


def _carmax_pool(deal):
    """Return CarMax pool_performance for a deal, normalized and chrono-sorted."""
    if not carmax_available():
        return pd.DataFrame()
    pool = q("SELECT * FROM pool_performance WHERE deal=?", (deal,), db=CARMAX_DB)
    if pool.empty:
        return pool
    pool["period"] = pool["distribution_date"].apply(nd)
    pool = pool.sort_values("period").reset_index(drop=True)
    # Derive cum_net_losses when the reporting cert populated only period flows.
    # CarMax ingestion fills cumulative_net_losses for some deals and leaves it
    # NULL for others; net_charged_off_amount is similarly sparse. We compute a
    # derived column `cum_net_loss_derived` that falls back to cumsum of
    # period net charge-offs so every deal has *something* to plot.
    if "cumulative_net_losses" in pool.columns and pool["cumulative_net_losses"].notna().any():
        pool["cum_net_loss_derived"] = pool["cumulative_net_losses"].ffill()
    elif "net_charged_off_amount" in pool.columns and pool["net_charged_off_amount"].notna().any():
        pool["cum_net_loss_derived"] = pool["net_charged_off_amount"].fillna(0).cumsum()
    else:
        pool["cum_net_loss_derived"] = pd.NA
    return pool


def get_carmax_orig_bal(deal):
    """Return the deal's original cutoff pool balance for CarMax.

    CarMax ingestion populates `initial_pool_balance` on every pool row for the
    deals where the servicer cert reports it; we also fall back to the first
    beginning_pool_balance we have on file. (We don't have servicer-cert HTML
    cached for CarMax the way we do for Carvana, so the cert-parse fallback
    used in get_orig_bal() doesn't apply here.)
    """
    if not carmax_available():
        return None
    df = q(
        "SELECT initial_pool_balance FROM pool_performance "
        "WHERE deal=? AND initial_pool_balance IS NOT NULL LIMIT 1",
        (deal,), db=CARMAX_DB,
    )
    if not df.empty and df.iloc[0]["initial_pool_balance"]:
        return float(df.iloc[0]["initial_pool_balance"])
    df = q(
        "SELECT MAX(beginning_pool_balance) AS m FROM pool_performance "
        "WHERE deal=? AND beginning_pool_balance > 0",
        (deal,), db=CARMAX_DB,
    )
    if not df.empty and df.iloc[0]["m"]:
        return float(df.iloc[0]["m"])
    return None


def generate_carmax_deal_content(deal):
    """Per-deal CarMax tab content. Mirrors generate_deal_content() layout
    (Pool Summary / Delinquencies / Losses / Documents) but reads from the
    CarMax DB and degrades gracefully where loan-level data is absent.

    Returns (metrics_html, tabs_content) or None.
    """
    pool = _carmax_pool(deal)
    if pool.empty:
        logger.warning(f"[CARMX {deal}] No pool_performance, skipping")
        return None

    ORIG_BAL = get_carmax_orig_bal(deal)
    x = pool["period"].tolist()
    last = pool.iloc[-1]

    # Last row may have stale/NULL values for some columns (e.g. cum_net_loss
    # isn't reported on every cert). Pick the last non-null value instead.
    def _last_nn(col):
        if col not in pool.columns:
            return None
        s = pool[col].dropna()
        return s.iloc[-1] if not s.empty else None

    last_bal = _last_nn("ending_pool_balance")
    last_count = _last_nn("ending_pool_count")
    last_cum_loss = _last_nn("cum_net_loss_derived")
    last_dq_bal = _last_nn("total_delinquent_balance")

    sections = {}

    # ── POOL SUMMARY ──
    h = ""
    bal = pool["ending_pool_balance"].ffill()
    if bal.notna().any():
        bal_m = [round(v / 1e6, 1) if pd.notna(v) else None for v in bal.tolist()]
        h += chart(
            [{"x": x, "y": bal_m, "type": "scatter", "fill": "tozeroy",
              "line": {"color": "#F47920"}, "name": "Balance"}],
            {"title": "Remaining Pool Balance ($M)",
             "yaxis": {"ticksuffix": "M", "tickprefix": "$"},
             "hovermode": "x unified"},
        )
    if "ending_pool_count" in pool.columns and pool["ending_pool_count"].notna().any():
        h += chart(
            [{"x": x, "y": [int(v) if pd.notna(v) else None for v in pool["ending_pool_count"].tolist()],
              "type": "scatter", "line": {"color": "#FFD200"}, "name": "Loans"}],
            {"title": "Active Loan Count", "hovermode": "x unified"},
        )
    if "weighted_avg_apr" in pool.columns and pool["weighted_avg_apr"].notna().any():
        h += chart(
            [{"x": x, "y": pool["weighted_avg_apr"].tolist(), "type": "scatter",
              "line": {"color": "#F47920"}, "name": "Avg Consumer Rate"}],
            {"title": "Avg Consumer Rate (Weighted APR)",
             "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified"},
        )
    if not h:
        h = "<p>No pool performance data available.</p>"
    sections["Pool Summary"] = h

    # ── DELINQUENCIES ──
    # CarMax reports dollar balances and counts by bucket on the servicer
    # certificate. We plot the rate (balance / ending_pool_balance) as a
    # stacked area, matching the Carvana layout.
    h = ""
    dq_cols = [
        ("delinquent_31_60_balance", "31-60d", "#FFC107"),
        ("delinquent_61_90_balance", "61-90d", "#FF9800"),
        ("delinquent_91_120_balance", "91-120d", "#FF5722"),
        ("delinquent_121_plus_balance", "121+d", "#D32F2F"),
    ]
    # Tail-amortization mask (audit #9). Rate denominator becomes noisy once
    # the pool runs below 10% of its original balance; mask rates there and
    # render raw dollar balances as a companion chart.
    _tail_mask = [
        (float(e) / ORIG_BAL) < 0.10 if (pd.notna(e) and e and ORIG_BAL) else False
        for e in pool["ending_pool_balance"].tolist()
    ]
    traces = []
    bal_traces = []
    have_any_dq = False
    for col, label, color in dq_cols:
        if col in pool.columns and pool[col].notna().any():
            rates = [
                (float(b) / float(e)) if (pd.notna(b) and pd.notna(e) and e and not m)
                else None
                for b, e, m in zip(pool[col].tolist(),
                                   pool["ending_pool_balance"].tolist(),
                                   _tail_mask)
            ]
            traces.append({
                "x": x, "y": rates, "name": label,
                "stackgroup": "dq", "line": {"color": color},
            })
            bal_traces.append({
                "x": x, "y": pool[col].tolist(), "name": label,
                "stackgroup": "dq", "line": {"color": color},
            })
            have_any_dq = True
    if have_any_dq:
        h += chart(traces, {
            "title": "Delinquency Rates (% of Pool)",
            "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified",
        })
        if any(_tail_mask) and bal_traces:
            h += chart(bal_traces, {
                "title": "Delinquency Balances ($) — pool &lt; 10% of original",
                "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified",
            })
            h += ('<p style="font-size:.75rem;color:#666;margin-top:-4px;">'
                  "Rate trace is suppressed once the pool amortizes below 10% "
                  "of its original balance — the denominator becomes too small "
                  "to be meaningful. Raw dollar balances remain visible."
                  "</p>")
    # Trigger vs actual (CarMax reports delinquency_trigger_actual; trigger
    # level may be absent on many certs)
    if "delinquency_trigger_actual" in pool.columns and pool["delinquency_trigger_actual"].notna().any():
        trig = pool.dropna(subset=["delinquency_trigger_actual"])
        t_traces = [{
            "x": trig["period"].tolist(),
            "y": trig["delinquency_trigger_actual"].tolist(),
            "name": "Actual", "line": {"color": "#F47920"},
        }]
        if "delinquency_trigger_level" in pool.columns and pool["delinquency_trigger_level"].notna().any():
            tg = pool.dropna(subset=["delinquency_trigger_level"])
            t_traces.append({
                "x": tg["period"].tolist(),
                "y": tg["delinquency_trigger_level"].tolist(),
                "name": "Trigger", "line": {"dash": "dash", "color": "red"},
            })
        h += chart(t_traces, {
            "title": "Delinquency Trigger vs Actual",
            "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified",
        })
    # Latest-period DQ table
    if last_bal:
        dq_tbl_rows = []
        for col, label, _ in dq_cols:
            cnt_col = col.replace("_balance", "_count")
            b = last.get(col)
            c = last.get(cnt_col) if cnt_col in pool.columns else None
            if pd.notna(b):
                pct = f"{float(b) / float(last_bal):.2%}" if last_bal else "-"
                dq_tbl_rows.append({
                    "Bucket": label,
                    "Count": f"{int(c):,}" if pd.notna(c) else "-",
                    "Balance": fm(float(b)),
                    "% Pool": pct,
                })
        total_b = last.get("total_delinquent_balance")
        if pd.notna(total_b):
            dq_tbl_rows.append({
                "Bucket": "Total",
                "Count": f"{int(last.get('delinquent_31_60_count') or 0) + int(last.get('delinquent_61_90_count') or 0) + int(last.get('delinquent_91_120_count') or 0) + int(last.get('delinquent_121_plus_count') or 0):,}",
                "Balance": fm(float(total_b)),
                "% Pool": f"{float(total_b) / float(last_bal):.2%}" if last_bal else "-",
            })
        if dq_tbl_rows:
            h += "<h3>Latest Period</h3>" + table_html(pd.DataFrame(dq_tbl_rows))

    if not h:
        h = "<p>No delinquency data available.</p>"
    sections["Delinquencies"] = h

    # ── LOSSES ──
    h = ""
    if ORIG_BAL and pool["cum_net_loss_derived"].notna().any():
        loss_rate = [
            (float(v) / ORIG_BAL) if pd.notna(v) else None
            for v in pool["cum_net_loss_derived"].tolist()
        ]
        h += chart(
            [{"x": x, "y": loss_rate, "type": "scatter", "fill": "tozeroy",
              "line": {"color": "#D32F2F"}}],
            {"title": f"Cumulative Net Loss Rate (% of {fm(ORIG_BAL)})",
             "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified"},
        )
    # Gross / net / recoveries (cumulative) — use cumulative_gross_losses and
    # cumulative_liquidation_proceeds where reported, cumsum of period flows
    # otherwise.
    cum_gross = pool.get("cumulative_gross_losses")
    cum_rec = pool.get("cumulative_liquidation_proceeds")
    if cum_gross is None or not cum_gross.notna().any():
        if "gross_charged_off_amount" in pool.columns and pool["gross_charged_off_amount"].notna().any():
            cum_gross = pool["gross_charged_off_amount"].fillna(0).cumsum()
    if cum_rec is None or not cum_rec.notna().any():
        if "recoveries" in pool.columns and pool["recoveries"].notna().any():
            cum_rec = pool["recoveries"].fillna(0).cumsum()

    gross_vals = cum_gross.tolist() if cum_gross is not None and cum_gross.notna().any() else None
    rec_vals = cum_rec.tolist() if cum_rec is not None and cum_rec.notna().any() else None
    net_vals = pool["cum_net_loss_derived"].tolist() if pool["cum_net_loss_derived"].notna().any() else None
    if any([gross_vals, rec_vals, net_vals]):
        traces = []
        if gross_vals:
            traces.append({"x": x, "y": gross_vals, "name": "Gross Chargeoffs",
                           "line": {"color": "#D32F2F"}})
        if rec_vals:
            traces.append({"x": x, "y": rec_vals, "name": "Liquidation Proceeds",
                           "line": {"color": "#4CAF50"}})
        if net_vals:
            traces.append({"x": x, "y": net_vals, "name": "Net Losses",
                           "line": {"color": "#FF9800", "dash": "dash"}})
            # Restatement envelope + markers (audit finding #7). Servicers
            # sometimes restate cumulative_net_losses downward in a later
            # period. Overlay the running max (monotone envelope) and drop
            # a subtle marker where the raw series ticks down.
            envelope, markers_x, markers_y = _restatement_overlay(x, net_vals)
            if envelope is not None:
                traces.append({"x": x, "y": envelope, "name": "Net Losses (monotone envelope)",
                               "line": {"color": "#FF9800", "dash": "dot", "width": 1},
                               "opacity": 0.5})
            if markers_x:
                traces.append({
                    "x": markers_x, "y": markers_y, "name": "Restatement",
                    "mode": "markers", "type": "scatter",
                    "marker": {"symbol": "triangle-down", "size": 9, "color": "#607D8B"},
                    "hovertemplate": "Servicer restated cumulative loss on %{x}<extra></extra>",
                })
        h += chart(traces, {
            "title": "Cumulative Gross Losses vs Recoveries",
            "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified",
        })
    # Monthly flows
    co_flow = pool.get("gross_charged_off_amount")
    rec_flow = pool.get("recoveries")
    if ((co_flow is not None and co_flow.notna().any())
            or (rec_flow is not None and rec_flow.notna().any())):
        traces = []
        if co_flow is not None and co_flow.notna().any():
            traces.append({"x": x, "y": co_flow.tolist(), "name": "Chargeoffs",
                           "type": "bar", "marker": {"color": "#D32F2F"}})
        if rec_flow is not None and rec_flow.notna().any():
            traces.append({"x": x, "y": rec_flow.tolist(), "name": "Recoveries",
                           "type": "bar", "marker": {"color": "#4CAF50"}})
        h += chart(traces, {
            "title": "Monthly Chargeoffs vs Recoveries", "barmode": "group",
            "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified",
        })

    h += ('<p style="font-size:.75rem;color:#666;margin-top:8px;">'
          "Loan-level loss breakdowns (by credit score, interest rate) require "
          "ABS-EE loan tape ingestion which is not yet complete for CarMax. "
          "Pool-level losses above are parsed from the servicer certificate.</p>")
    sections["Losses"] = h

    # ── CASH WATERFALL ──
    # Mirrors the Carvana servicer-certificate waterfall.  CarMax pool_performance
    # has: interest_collections, principal_collections, liquidation_proceeds,
    # actual_servicing_fee, regular_pda, residual_cash, total_deposited.
    h = ""
    wf_avail = (not pool.empty
                and any(c in pool.columns and pool[c].notna().any()
                        for c in ["total_deposited", "interest_collections",
                                  "principal_collections", "residual_cash"]))
    if wf_avail:
        # ── Stacked bar: collections breakdown ──
        bar_traces = []
        bar_cols = [
            ("interest_collections", "Interest Collections", "#1976D2"),
            ("principal_collections", "Principal Collections", "#388E3C"),
            ("liquidation_proceeds", "Liquidation Proceeds", "#FF9800"),
        ]
        for col, name, color in bar_cols:
            if col in pool.columns and pool[col].notna().any():
                bar_traces.append({
                    "x": x, "y": pool[col].fillna(0).tolist(),
                    "name": name, "type": "bar",
                    "marker": {"color": color},
                })
        # Line overlay: servicing fee, principal distributable, residual
        line_cols = [
            ("actual_servicing_fee", "Servicing Fee", "#9C27B0", "dot"),
            ("regular_pda", "Principal Distributable", "#607D8B", "dash"),
            ("residual_cash", "Residual (to Equity)", "#F47920", "solid"),
        ]
        for col, name, color, dash in line_cols:
            if col in pool.columns and pool[col].notna().any():
                bar_traces.append({
                    "x": x, "y": pool[col].fillna(0).tolist(),
                    "name": name, "type": "scatter",
                    "line": {"color": color, "dash": dash},
                })
        if bar_traces:
            h += chart(bar_traces, {
                "title": "Monthly Cash Waterfall",
                "barmode": "stack",
                "yaxis": {"tickformat": "$,.0f"},
                "hovermode": "x unified",
            })

        # ── Waterfall table ──
        wf_cols = ["period"]
        wf_names = ["Period"]
        for col, name in [("total_deposited", "Total Deposited"),
                          ("interest_collections", "Interest Collections"),
                          ("principal_collections", "Principal Collections"),
                          ("liquidation_proceeds", "Liquidation Proceeds"),
                          ("actual_servicing_fee", "Servicing Fee"),
                          ("regular_pda", "Principal Dist"),
                          ("residual_cash", "Residual (to Equity)")]:
            if col in pool.columns and pool[col].notna().any():
                wf_cols.append(col)
                wf_names.append(name)
        if len(wf_cols) > 1:
            wf_pool = pool[wf_cols].copy()
            wf_pool.columns = wf_names
            sums_wf = wf_pool.select_dtypes(include="number").sum()
            sr_wf = pd.DataFrame([["TOTAL"] + sums_wf.tolist()], columns=wf_pool.columns)
            wf_pool_all = pd.concat([wf_pool, sr_wf], ignore_index=True)
            wf_pool_fmt = wf_pool_all.copy()
            for c in wf_pool_fmt.columns[1:]:
                wf_pool_fmt[c] = wf_pool_all[c].apply(lambda v: fm(v) if pd.notna(v) and v != 0 else "-")
            h += table_html(wf_pool_fmt)

        # ── Cumulative residual cash chart ──
        if "residual_cash" in pool.columns and pool["residual_cash"].notna().any():
            res_data = pool[pool["residual_cash"].notna()]
            if not res_data.empty and ORIG_BAL and ORIG_BAL > 0:
                cum_res = res_data["residual_cash"].cumsum()
                cum_res_pct = cum_res / ORIG_BAL
                h += chart([{"x": res_data["period"].tolist(), "y": cum_res_pct.tolist(),
                             "type": "scatter", "fill": "tozeroy", "line": {"color": "#388E3C"}}],
                           {"title": "Cumulative Cash to Residual (% of Original Balance)",
                            "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified"})

    if not h:
        h = "<p>No cash waterfall data available for this deal.</p>"
    sections["Cash Waterfall"] = h

    # ── RECOVERY ──
    # Pool-level recovery analysis from pool_performance columns.
    # CarMax doesn't have loan-level loan_loss_summary, so we use aggregate
    # monthly flows: recoveries, gross_charged_off_amount, net_charged_off_amount,
    # and cumulative counterparts.
    h = ""
    has_recovery_data = (not pool.empty
                         and "recoveries" in pool.columns
                         and pool["recoveries"].notna().any())
    has_gross_co = (not pool.empty
                    and "gross_charged_off_amount" in pool.columns
                    and pool["gross_charged_off_amount"].notna().any())

    if has_recovery_data or has_gross_co:
        # ── Monthly flows: gross charge-offs vs recoveries vs net losses ──
        flow_traces = []
        if has_gross_co:
            flow_traces.append({
                "x": x, "y": pool["gross_charged_off_amount"].fillna(0).tolist(),
                "name": "Gross Charge-Offs", "type": "bar",
                "marker": {"color": "#D32F2F"},
            })
        if has_recovery_data:
            flow_traces.append({
                "x": x, "y": pool["recoveries"].fillna(0).tolist(),
                "name": "Recoveries", "type": "bar",
                "marker": {"color": "#4CAF50"},
            })
        net_co_col = None
        if "net_charged_off_amount" in pool.columns and pool["net_charged_off_amount"].notna().any():
            net_co_col = "net_charged_off_amount"
        if net_co_col:
            flow_traces.append({
                "x": x, "y": pool[net_co_col].fillna(0).tolist(),
                "name": "Net Losses", "type": "scatter",
                "line": {"color": "#FF9800", "dash": "dash"},
            })
        if flow_traces:
            h += chart(flow_traces, {
                "title": "Monthly Gross Charge-Offs vs Recoveries",
                "barmode": "group",
                "yaxis": {"tickformat": "$,.0f"},
                "hovermode": "x unified",
            })

        # ── Recovery rate over time ──
        if has_gross_co and has_recovery_data:
            # Trailing-12 recovery rate (smoothed) — ratio of sum(recoveries) / sum(gross_co) over rolling 12 periods
            gross_s = pool["gross_charged_off_amount"].fillna(0)
            rec_s = pool["recoveries"].fillna(0)
            roll_gross = gross_s.rolling(12, min_periods=3).sum()
            roll_rec = rec_s.rolling(12, min_periods=3).sum()
            roll_rate = (roll_rec / roll_gross.replace(0, float("nan")))
            if roll_rate.notna().any():
                h += chart([{
                    "x": x, "y": [round(v, 4) if pd.notna(v) else None for v in roll_rate.tolist()],
                    "type": "scatter", "line": {"color": "#1976D2"},
                }], {
                    "title": "Trailing-12 Recovery Rate (Recoveries / Gross Charge-Offs)",
                    "yaxis": {"tickformat": ".1%"},
                    "hovermode": "x unified",
                })

        # ── Cumulative view ──
        cum_traces = []
        # Use reported cumulative columns if available, else cumsum
        _cum_gross = pool.get("cumulative_gross_losses")
        if _cum_gross is None or not _cum_gross.notna().any():
            if has_gross_co:
                _cum_gross = pool["gross_charged_off_amount"].fillna(0).cumsum()
        _cum_rec = pool.get("cumulative_liquidation_proceeds")
        if _cum_rec is None or not _cum_rec.notna().any():
            if has_recovery_data:
                _cum_rec = pool["recoveries"].fillna(0).cumsum()
        _cum_net = pool.get("cumulative_net_losses")
        if _cum_net is None or not _cum_net.notna().any():
            if "cum_net_loss_derived" in pool.columns and pool["cum_net_loss_derived"].notna().any():
                _cum_net = pool["cum_net_loss_derived"]

        if _cum_gross is not None and _cum_gross.notna().any():
            cum_traces.append({"x": x, "y": _cum_gross.tolist(),
                               "name": "Cum Gross Losses", "line": {"color": "#D32F2F"}})
        if _cum_rec is not None and _cum_rec.notna().any():
            cum_traces.append({"x": x, "y": _cum_rec.tolist(),
                               "name": "Cum Recoveries", "line": {"color": "#4CAF50"}})
        if _cum_net is not None and _cum_net.notna().any():
            cum_traces.append({"x": x, "y": _cum_net.tolist(),
                               "name": "Cum Net Losses",
                               "line": {"color": "#FF9800", "dash": "dash"}})
        if cum_traces:
            h += chart(cum_traces, {
                "title": "Cumulative Gross Losses, Recoveries & Net Losses",
                "yaxis": {"tickformat": "$,.0f"},
                "hovermode": "x unified",
            })

        # ── Recovery data table ──
        rec_tbl_cols = ["period"]
        rec_tbl_names = ["Period"]
        for col, name in [("gross_charged_off_amount", "Gross Charge-Offs"),
                          ("recoveries", "Recoveries"),
                          ("net_charged_off_amount", "Net Losses")]:
            if col in pool.columns and pool[col].notna().any():
                rec_tbl_cols.append(col)
                rec_tbl_names.append(name)
        if len(rec_tbl_cols) > 1:
            rec_tbl = pool[rec_tbl_cols].copy()
            rec_tbl.columns = rec_tbl_names
            sums_r = rec_tbl.select_dtypes(include="number").sum()
            sr_r = pd.DataFrame([["TOTAL"] + sums_r.tolist()], columns=rec_tbl.columns)
            rec_tbl_all = pd.concat([rec_tbl, sr_r], ignore_index=True)
            rec_tbl_fmt = rec_tbl_all.copy()
            for c in rec_tbl_fmt.columns[1:]:
                rec_tbl_fmt[c] = rec_tbl_all[c].apply(lambda v: fm(v) if pd.notna(v) and v != 0 else "-")
            h += table_html(rec_tbl_fmt)

        # ── Summary metrics ──
        total_gross = pool["gross_charged_off_amount"].fillna(0).sum() if has_gross_co else 0
        total_rec = pool["recoveries"].fillna(0).sum() if has_recovery_data else 0
        overall_rate = total_rec / total_gross if total_gross > 0 else 0
        h = (f'<div class="metrics">'
             f'<div class="metric"><div class="mv">{fm(total_gross)}</div><div class="ml">Total Gross Charge-Offs</div></div>'
             f'<div class="metric"><div class="mv">{fm(total_rec)}</div><div class="ml">Total Recoveries</div></div>'
             f'<div class="metric"><div class="mv">{overall_rate:.1%}</div><div class="ml">Overall Recovery Rate</div></div>'
             f'</div>') + h

    if not h:
        h = "<p>No recovery data available for this deal.</p>"
    sections["Recovery"] = h

    # ── NOTES & OC ──
    # Mirrors the Carvana Notes & OC block (generate_deal_content). CarMax
    # ingestion now populates note_balance_a1..a4/b/c/d, aggregate_note_balance,
    # reserve_account_balance and overcollateralization_amount on every deal
    # (commit 84a7ebb). `dist_date_iso` orders chronologically. Carvana's
    # `notes` table isn't populated for CarMax, so we don't attempt a
    # subordination-ratio view.
    h = ""
    if not pool.empty:
        nc = [c for c in ["note_balance_a1","note_balance_a2","note_balance_a3","note_balance_a4",
                           "note_balance_b","note_balance_c","note_balance_d"]
              if c in pool.columns and pool[c].notna().any()
              and (pool[c].fillna(0) > 0).any()]  # omit class that is always 0
        if nc:
            traces = []
            for c in nc:
                traces.append({"x": pool["period"].tolist(), "y": pool[c].fillna(0).tolist(),
                               "name": c.replace("note_balance_","").upper(),
                               "stackgroup": "notes"})
            h += chart(traces, {"title": "Note Balances by Class",
                                "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})
        # Reserve account + OC lines (separate chart — different magnitudes)
        oc_traces = []
        if "overcollateralization_amount" in pool.columns and pool["overcollateralization_amount"].notna().any():
            oc_nn = pool.dropna(subset=["overcollateralization_amount"])
            oc_traces.append({"x": oc_nn["period"].tolist(),
                              "y": oc_nn["overcollateralization_amount"].tolist(),
                              "name": "Overcollateralization",
                              "line": {"color": "#F47920"}})
        if "reserve_account_balance" in pool.columns and pool["reserve_account_balance"].notna().any():
            rb_nn = pool.dropna(subset=["reserve_account_balance"])
            oc_traces.append({"x": rb_nn["period"].tolist(),
                              "y": rb_nn["reserve_account_balance"].tolist(),
                              "name": "Reserve Account",
                              "line": {"color": "#FFD200"}})
        if oc_traces:
            h += chart(oc_traces, {"title": "Overcollateralization & Reserve Account",
                                   "yaxis": {"tickformat": "$,.0f"},
                                   "hovermode": "x unified"})
    if not h:
        h = "<p>No note-balance or credit-enhancement data available.</p>"
    sections["Notes & OC"] = h

    # ── DOCUMENTS ──
    h = ""
    try:
        certs = q(
            "SELECT filing_date, servicer_cert_url, accession_number FROM filings "
            "WHERE deal=? AND servicer_cert_url IS NOT NULL ORDER BY filing_date DESC",
            (deal,), db=CARMAX_DB,
        )
        if not certs.empty:
            h += "<h3>Servicer Certificates</h3>"
            cert_rows = []
            for _, row in certs.iterrows():
                fd = row["filing_date"]
                try:
                    dt_obj = datetime.strptime(str(fd).strip()[:10], "%Y-%m-%d")
                    date_display = dt_obj.strftime("%b %Y")
                except (ValueError, TypeError):
                    date_display = str(fd)[:10] if fd else "Unknown"
                link = f'<a href="{row["servicer_cert_url"]}" target="_blank" rel="noopener">SEC&nbsp;Filing</a>'
                cert_rows.append({"Date": date_display, "Download": link})
            h += table_html(pd.DataFrame(cert_rows), cls="compare")
    except Exception as e:
        logger.warning(f"[CARMX {deal}] Error building servicer cert links: {e}")

    try:
        from carmax_abs.config import DEALS as CARMAX_DEAL_REGISTRY
        deal_info = CARMAX_DEAL_REGISTRY.get(deal, {})
        cik = deal_info.get("cik", "")
        entity = deal_info.get("entity_name", f"CarMax Auto Owner Trust {deal}")
        if cik:
            h += "<h3>Prospectus &amp; Other Filings</h3>"
            edgar_base = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
            filing_links = [
                {"Document": "All SEC Filings",
                 "Description": f"Complete filing history for {entity}",
                 "Link": f'<a href="{edgar_base}&type=&dateb=&owner=include&count=40" target="_blank" rel="noopener">EDGAR</a>'},
                {"Document": "Prospectus (424B)",
                 "Description": "Offering prospectus and supplements",
                 "Link": f'<a href="{edgar_base}&type=424B&dateb=&owner=include&count=10" target="_blank" rel="noopener">EDGAR</a>'},
                {"Document": "Annual Reports (10-K)",
                 "Description": "Annual reports filed with SEC",
                 "Link": f'<a href="{edgar_base}&type=10-K&dateb=&owner=include&count=10" target="_blank" rel="noopener">EDGAR</a>'},
                {"Document": "Current Reports (8-K)",
                 "Description": "Material event disclosures",
                 "Link": f'<a href="{edgar_base}&type=8-K&dateb=&owner=include&count=10" target="_blank" rel="noopener">EDGAR</a>'},
            ]
            h += table_html(pd.DataFrame(filing_links), cls="compare")
    except Exception as e:
        logger.warning(f"[CARMX {deal}] Error building prospectus links: {e}")

    if not h:
        h = "<p>No documents available for this deal.</p>"
    sections["Documents"] = h

    # ── Metric strip ──
    pool_factor_display = (f"{float(last_bal) / ORIG_BAL:.1%}"
                           if (last_bal and ORIG_BAL and ORIG_BAL > 0) else "-")
    cum_loss_display = (f"{float(last_cum_loss) / ORIG_BAL:.2%}"
                        if (last_cum_loss is not None and ORIG_BAL and ORIG_BAL > 0) else "-")
    dq_display = (f"{float(last_dq_bal) / float(last_bal):.2%}"
                  if (last_dq_bal is not None and last_bal) else "-")

    loan_count_display = f"{int(last_count):,}" if (last_count is not None and pd.notna(last_count)) else "-"
    metrics_html = f"""<div class="metrics">
<div class="metric"><div class="mv">{fm(ORIG_BAL) if ORIG_BAL else '-'}</div><div class="ml">Original Balance</div></div>
<div class="metric"><div class="mv">{fm(last_bal) if last_bal else '-'}</div><div class="ml">Current Balance</div></div>
<div class="metric"><div class="mv">{pool_factor_display}</div><div class="ml">Pool Factor</div></div>
<div class="metric"><div class="mv">{loan_count_display}</div><div class="ml">Active Loans</div></div>
<div class="metric"><div class="mv">{cum_loss_display}</div><div class="ml">Cum Loss Rate</div></div>
<div class="metric"><div class="mv">{dq_display}</div><div class="ml">Total DQ Rate</div></div>
</div>"""

    # Deal slugs must not collide with Carvana deal slugs. Carvana deals look
    # like "2021-P1" and already slugify to "2021_P1"; CarMax deals look like
    # "2021-1" which would slugify to "2021_1" — no collision with Carvana's
    # "-P"/"-N" suffixed names, but we prefix with "cm_" to remove any doubt.
    deal_safe = f"cm_{deal.replace('-', '_')}"
    tabs_html = ""; content_html = ""; first = True
    for name, body in sections.items():
        tid = f"{deal_safe}_{name.replace(' ','_').replace('&','and')}"
        tabs_html += f'<button class="tab{" active" if first else ""}" onclick="showTab(\'{tid}\',this)">{name}</button>\n'
        content_html += f'<div id="{tid}" class="tc" style="display:{"block" if first else "none"}">{body}</div>\n'
        first = False

    return metrics_html, f'<div class="tabs">{tabs_html}</div>\n{content_html}'


def _carmax_pool_time_series(deal):
    """Return normalized pool_performance for a CarMax deal with derived columns
    needed by the comparison tabs. Returns an empty frame if no data."""
    return _carmax_pool(deal)


def _carmax_traces(deals, color_map=None):
    """Compute comparison traces (pool factor by age, cum net loss by age,
    loss vs pool factor, excess spread (stub), 30+ DQ by age, annualized CO
    rate by age) for a list of CarMax deals. Returns a dict with keys:

        pf, pf_loss, cum_loss_age, dq, co, spread

    each a list of Plotly trace dicts. color_map is {deal: hex}; if None, the
    CARMAX_COLORS palette is cycled.
    """
    out = {"pf": [], "pf_loss": [], "cum_loss_age": [], "dq": [], "co": [], "spread": []}
    if not carmax_available():
        return out
    for i, deal in enumerate(deals):
        color = color_map[deal] if color_map else CARMAX_COLORS[i % len(CARMAX_COLORS)]
        pool = _carmax_pool(deal)
        if pool.empty:
            continue
        orig_bal = get_carmax_orig_bal(deal)
        if not orig_bal or orig_bal <= 0:
            continue
        age = list(range(1, len(pool) + 1))

        # Pool factor by age — ending balance / initial pool balance
        if "ending_pool_balance" in pool.columns and pool["ending_pool_balance"].notna().any():
            pf = [(float(v) / orig_bal) if pd.notna(v) else None
                  for v in pool["ending_pool_balance"].tolist()]
            out["pf"].append({
                "x": age, "y": pf, "type": "scatter", "mode": "lines",
                "name": f"CARMX {deal}", "line": {"color": color},
            })

        # Cum net loss rate by age
        if pool["cum_net_loss_derived"].notna().any():
            cr = [(float(v) / orig_bal) if pd.notna(v) else None
                  for v in pool["cum_net_loss_derived"].tolist()]
            out["cum_loss_age"].append({
                "x": age, "y": cr, "type": "scatter", "mode": "lines",
                "name": f"CARMX {deal}", "line": {"color": color},
            })

            # Loss vs pool factor — x=pool factor, y=cum net loss rate
            if "ending_pool_balance" in pool.columns and pool["ending_pool_balance"].notna().any():
                xs, ys = [], []
                for epb, cn in zip(pool["ending_pool_balance"].tolist(),
                                   pool["cum_net_loss_derived"].tolist()):
                    if pd.notna(epb) and pd.notna(cn) and epb > 0:
                        xs.append(float(epb) / orig_bal)
                        ys.append(float(cn) / orig_bal)
                if xs:
                    out["pf_loss"].append({
                        "x": xs, "y": ys, "type": "scatter",
                        "mode": "lines+markers", "name": f"CARMX {deal}",
                        "line": {"color": color}, "marker": {"size": 4},
                    })

        # 30+ DQ rate by age
        if (
            "total_delinquent_balance" in pool.columns
            and pool["total_delinquent_balance"].notna().any()
            and "ending_pool_balance" in pool.columns
        ):
            dq = []
            for tdq, epb in zip(pool["total_delinquent_balance"].tolist(),
                                pool["ending_pool_balance"].tolist()):
                if pd.notna(tdq) and pd.notna(epb) and epb > 0:
                    dq.append(float(tdq) / float(epb))
                else:
                    dq.append(None)
            out["dq"].append({
                "x": age, "y": dq, "type": "scatter", "mode": "lines",
                "name": f"CARMX {deal}", "line": {"color": color},
            })

        # Annualized net charge-off rate by age — uses net_charged_off_amount
        # where populated; requires a prior-period balance as the denominator.
        if (
            "net_charged_off_amount" in pool.columns
            and pool["net_charged_off_amount"].notna().any()
            and "beginning_pool_balance" in pool.columns
        ):
            co_x, co_y = [], []
            for j, row in pool.iterrows():
                nco = row.get("net_charged_off_amount")
                pb = row.get("beginning_pool_balance")
                if pd.notna(nco) and pd.notna(pb) and float(pb) > 0:
                    co_x.append(j + 1)
                    co_y.append((float(nco) * 12.0) / float(pb))
            if co_x:
                out["co"].append({
                    "x": co_x, "y": co_y, "type": "scatter", "mode": "lines",
                    "name": f"CARMX {deal}", "line": {"color": color},
                })

        # Excess spread — WAC minus cost-of-debt. CarMax pool has
        # weighted_avg_apr and total_note_interest + aggregate_note_balance
        # on (some) rows, matching the Carvana definition.
        wac_col = pool.get("weighted_avg_apr")
        ni_col = pool.get("total_note_interest")
        nb_col = pool.get("aggregate_note_balance")
        if (
            wac_col is not None and wac_col.notna().any()
            and ni_col is not None and ni_col.notna().any()
            and nb_col is not None and nb_col.notna().any()
        ):
            xs, ys = [], []
            for j, row in pool.iterrows():
                w = row.get("weighted_avg_apr")
                ni = row.get("total_note_interest")
                nb = row.get("aggregate_note_balance")
                if pd.notna(w) and pd.notna(ni) and pd.notna(nb) and float(nb) > 0 and float(ni) > 0:
                    cod = float(ni) / float(nb) * 12.0
                    if 0 < cod < 0.25:
                        xs.append(j + 1)
                        ys.append(float(w) - cod)
            # Drop first point (partial-accrual artifact) to match Carvana chart
            if len(xs) > 1:
                xs, ys = xs[1:], ys[1:]
            if xs:
                out["spread"].append({
                    "x": xs, "y": ys, "type": "scatter", "mode": "lines",
                    "name": f"CARMX {deal}", "line": {"color": color},
                })
    return out


def generate_carmax_comparison_content(deals, title):
    """CarMax Prime comparison tab. Mirrors generate_comparison_content() but
    pulls from the CarMax DB and uses the CARMAX_COLORS palette. Where CarMax
    lacks data (loan tapes, cert text), sections degrade gracefully."""
    if not carmax_available() or not deals:
        return "<p>CarMax data not available.</p>"
    h = ""

    # Summary table — minimal, pool-level only
    rows = []
    for deal in deals:
        orig = get_carmax_orig_bal(deal)
        pool = _carmax_pool(deal)
        last_bal = None
        if "ending_pool_balance" in pool.columns and pool["ending_pool_balance"].notna().any():
            last_bal = float(pool["ending_pool_balance"].dropna().iloc[-1])
        pf = (last_bal / orig) if (last_bal and orig) else None
        last_cn = None
        if pool["cum_net_loss_derived"].notna().any():
            last_cn = float(pool["cum_net_loss_derived"].dropna().iloc[-1])
        cum_loss = (last_cn / orig) if (last_cn is not None and orig) else None
        init_wac = curr_wac = None
        if "weighted_avg_apr" in pool.columns and pool["weighted_avg_apr"].notna().any():
            nonnull = pool["weighted_avg_apr"].dropna()
            init_wac = float(nonnull.iloc[0])
            curr_wac = float(nonnull.iloc[-1])
        rows.append({
            "Deal": f"CARMX {deal}",
            "Initial Avg Consumer Rate": f"{init_wac:.2%}" if init_wac is not None else "-",
            "Current Avg Consumer Rate": f"{curr_wac:.2%}" if curr_wac is not None else "-",
            "Init Balance": fm(orig) if orig else "-",
            "Pool Factor": f"{pf:.1%}" if pf is not None else "-",
            "Cum Loss": f"{cum_loss:.2%}" if cum_loss is not None else "-",
        })
    if rows:
        h += f"<h3>{title} — Summary</h3>" + table_html(pd.DataFrame(rows), cls="compare")

    t = _carmax_traces(deals)

    def _plot(bucket, layout):
        if t.get(bucket):
            return chart(t[bucket], layout, height=450)
        return ""

    h += _plot("pf", {
        "title": f"{title} — Pool Factor by Deal Age",
        "xaxis": {"title": "Deal Age (Months)"},
        "yaxis": {"tickformat": ".0%", "title": "Pool Factor (Remaining / Original)"},
        "hovermode": "x unified", "legend": {"orientation": "h", "y": -0.3},
    })
    h += _plot("cum_loss_age", {
        "title": f"{title} — Cumulative Net Loss Rate by Deal Age",
        "xaxis": {"title": "Deal Age (Months)"},
        "yaxis": {"tickformat": ".2%", "title": "Cum Net Loss (% of Orig Bal)"},
        "hovermode": "x unified", "legend": {"orientation": "h", "y": -0.3},
    })
    h += _plot("pf_loss", {
        "title": f"{title} — Cumulative Net Loss vs Pool Factor",
        "xaxis": {"title": "Pool Factor (Remaining / Original)",
                  "tickformat": ".0%", "autorange": "reversed"},
        "yaxis": {"tickformat": ".2%", "title": "Cum Net Loss (% of Orig Bal)"},
        "hovermode": "closest", "legend": {"orientation": "h", "y": -0.3},
    })
    h += _plot("dq", {
        "title": f"{title} — Total Delinquency Rate by Deal Age",
        "xaxis": {"title": "Deal Age (Months)"},
        "yaxis": {"tickformat": ".2%", "title": "Total DQ Balance / Pool Balance"},
        "hovermode": "x unified", "legend": {"orientation": "h", "y": -0.3},
    })
    h += _plot("co", {
        "title": f"{title} — Annualized Net Charge-Off Rate by Deal Age",
        "xaxis": {"title": "Deal Age (Months)"},
        "yaxis": {"tickformat": ".2%",
                  "title": "Net Charge-Offs × 12 / Prior Month Balance"},
        "hovermode": "x unified", "legend": {"orientation": "h", "y": -0.3},
    })
    h += _plot("spread", {
        "title": f"{title} — Excess Spread by Deal Age (Consumer Rate − Trust Cost of Debt)",
        "xaxis": {"title": "Deal Age (Months)"},
        "yaxis": {"tickformat": ".2%", "title": "Excess Spread"},
        "hovermode": "x unified", "legend": {"orientation": "h", "y": -0.3},
    })

    return h or "<p>No comparison data available.</p>"


def _carvana_prime_traces(deals, color_map):
    """Re-derive the Carvana Prime comparison traces using an explicit per-deal
    color map so the cross-issuer tab can put every Carvana deal in the blue
    family. Returns dict with same keys as _carmax_traces().

    This duplicates the trace-building logic from generate_comparison_content()
    — we can't reuse that function directly because it assembles a full HTML
    block with headings and a summary table, and because the color assignment
    there is positional via the COLORS palette.
    """
    out = {"pf": [], "pf_loss": [], "cum_loss_age": [], "dq": [], "co": [], "spread": []}
    note_bal_cols = {"A1": "note_balance_a1", "A2": "note_balance_a2", "A3": "note_balance_a3",
                     "A4": "note_balance_a4", "B": "note_balance_b", "C": "note_balance_c",
                     "D": "note_balance_d", "N": "note_balance_n"}

    for deal in deals:
        color = color_map.get(deal, "#1976D2")
        orig_bal = get_orig_bal(deal)
        if not orig_bal or orig_bal <= 0:
            continue

        # Cum net loss rate by age (cert-authoritative)
        series = _cum_net_loss_series(deal)
        if series:
            months = list(range(1, len(series) + 1))
            rates = [round(cn / orig_bal, 6) for _, cn in series]
            out["cum_loss_age"].append({
                "x": months, "y": rates, "type": "scatter", "mode": "lines",
                "name": f"Carvana {deal}", "line": {"color": color},
            })

        # Pool factor by age — from monthly_summary
        ms = q("SELECT reporting_period_end, total_balance, period_chargeoffs, period_recoveries "
               "FROM monthly_summary WHERE deal=? ORDER BY reporting_period_end", (deal,))
        if not ms.empty:
            ms["period"] = ms["reporting_period_end"].apply(nd)
            ms = ms.sort_values("period").reset_index(drop=True)
            ms["pool_factor"] = ms["total_balance"].astype(float) / orig_bal
            out["pf"].append({
                "x": list(range(1, len(ms) + 1)),
                "y": [round(v, 6) for v in ms["pool_factor"].tolist()],
                "type": "scatter", "mode": "lines", "name": f"Carvana {deal}",
                "line": {"color": color},
            })

            # Loss vs Pool Factor
            loss_series = _cum_net_loss_series(deal)
            if loss_series:
                pool_bal = q("SELECT distribution_date, ending_pool_balance FROM pool_performance "
                             "WHERE deal=?", (deal,))
                bal_by_dt = {}
                for _, r in pool_bal.iterrows():
                    if r["ending_pool_balance"]:
                        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                            try:
                                bal_by_dt[datetime.strptime(str(r["distribution_date"]).strip()[:10], fmt)] = float(r["ending_pool_balance"])
                                break
                            except (ValueError, TypeError):
                                pass
                pf_x, pf_y = [], []
                for dt, cn in loss_series:
                    bal = bal_by_dt.get(dt)
                    if bal is None:
                        continue
                    pf_x.append(round(bal / orig_bal, 6))
                    pf_y.append(round(cn / orig_bal, 6))
                if pf_x:
                    out["pf_loss"].append({
                        "x": pf_x, "y": pf_y, "type": "scatter",
                        "mode": "lines+markers", "name": f"Carvana {deal}",
                        "line": {"color": color}, "marker": {"size": 4},
                    })

            # 30+ DQ from cert series
            dq_series = _cert_dq_series(deal)
            if dq_series:
                out["dq"].append({
                    "x": list(range(1, len(dq_series) + 1)),
                    "y": [round(dq / epb, 6) if epb else 0 for _, dq, epb in dq_series],
                    "type": "scatter", "mode": "lines", "name": f"Carvana {deal}",
                    "line": {"color": color},
                })

            # Annualized net CO rate
            bal = ms["total_balance"].astype(float)
            prev_bal = bal.shift(1)
            net_co = (ms["period_chargeoffs"].fillna(0) - ms["period_recoveries"].fillna(0)).astype(float)
            co_rate = (net_co * 12.0) / prev_bal.where(prev_bal > 0)
            co_x, co_y = [], []
            for idx, v in enumerate(co_rate.tolist()):
                if idx == 0 or v is None or pd.isna(v):
                    continue
                co_x.append(idx + 1)
                co_y.append(round(float(v), 6))
            if co_x:
                out["co"].append({
                    "x": co_x, "y": co_y, "type": "scatter", "mode": "lines",
                    "name": f"Carvana {deal}", "line": {"color": color},
                })

        # Excess spread — replicate the shifted collection-month alignment
        pool = q("SELECT * FROM pool_performance WHERE deal=? ORDER BY dist_date_iso", (deal,))
        if pool.empty:
            continue
        pool["period"] = pool["distribution_date"].apply(nd)
        pool = pool.sort_values("period").reset_index(drop=True)

        def _ym(s):
            s = str(s).strip()
            if len(s) >= 7 and s[4] in "-/":
                try:
                    return (int(s[:4]), int(s[5:7]))
                except ValueError:
                    return None
            return None

        wac_by_col = {}
        if "weighted_avg_apr" in pool.columns and pool["weighted_avg_apr"].notna().any():
            for _, row in pool.iterrows():
                ym = _ym(row["period"])
                w = row["weighted_avg_apr"]
                if ym and pd.notna(w):
                    col_ym = (ym[0], ym[1] - 1) if ym[1] > 1 else (ym[0] - 1, 12)
                    wac_by_col[col_ym] = float(w)
        else:
            wac_ms = q("SELECT reporting_period_end, weighted_avg_coupon FROM monthly_summary "
                       "WHERE deal=? AND weighted_avg_coupon IS NOT NULL ORDER BY reporting_period_end", (deal,))
            for _, row in wac_ms.iterrows():
                ym = _ym(nd(row["reporting_period_end"]))
                if ym:
                    wac_by_col[ym] = float(row["weighted_avg_coupon"])

        try:
            notes_df = q("SELECT class, coupon_rate FROM notes WHERE deal=? AND coupon_rate IS NOT NULL", (deal,))
        except Exception:
            notes_df = pd.DataFrame()
        norm_rate_lookup = {}
        if not notes_df.empty:
            for cls, rate in zip(notes_df["class"], notes_df["coupon_rate"]):
                norm = cls.upper().replace("-", "").replace(" ", "").replace("CLASS", "")
                norm_rate_lookup[norm] = rate
        for col in note_bal_cols.values():
            if col in pool.columns:
                pool[col] = pool[col].ffill()

        cod_by_col = {}
        has_ni = "total_note_interest" in pool.columns
        has_nb = "aggregate_note_balance" in pool.columns
        for _, row in pool.iterrows():
            ym = _ym(row["period"])
            if not ym:
                continue
            col_ym = (ym[0], ym[1] - 1) if ym[1] > 1 else (ym[0] - 1, 12)
            cod_val = None
            if has_ni and has_nb:
                ni = row.get("total_note_interest")
                nb = row.get("aggregate_note_balance")
                if pd.notna(ni) and pd.notna(nb) and float(nb) > 0 and float(ni) > 0:
                    v = float(ni) / float(nb) * 12
                    if 0 < v < 0.25:
                        cod_val = v
            if cod_val is None and norm_rate_lookup:
                w_sum, t_bal = 0.0, 0.0
                for cls, col in note_bal_cols.items():
                    if col in pool.columns and cls in norm_rate_lookup:
                        bal = row.get(col)
                        if pd.notna(bal) and float(bal) > 0:
                            w_sum += norm_rate_lookup[cls] * float(bal)
                            t_bal += float(bal)
                if t_bal > 0:
                    cod_val = w_sum / t_bal
            if cod_val is not None:
                cod_by_col[col_ym] = cod_val

        keys = sorted(set(wac_by_col) & set(cod_by_col))
        if len(keys) > 1:
            keys = keys[1:]
        if keys:
            out["spread"].append({
                "x": list(range(1, len(keys) + 1)),
                "y": [round(wac_by_col[k] - cod_by_col[k], 6) for k in keys],
                "type": "scatter", "mode": "lines", "name": f"Carvana {deal}",
                "line": {"color": color},
            })

    return out


def generate_cross_issuer_comparison():
    """Carvana Prime + CarMax Prime on the same axes. Blue family for Carvana,
    orange/yellow family for CarMax. Every deal on the same five/six charts,
    indexed to deal age. Plotly's default legend-click-to-toggle lets users
    show/hide individual deals.
    """
    if not carmax_available():
        return "<p>CarMax data not available — cross-issuer tab disabled.</p>"

    carvana_prime = [d for d in PRIME_DEALS]
    carmax_prime = list(CARMAX_DEALS)

    # Color assignment: per-deal map so _carvana_prime_traces and _carmax_traces
    # pick the right color for each series.
    cv_map = {d: CARVANA_CROSS_COLORS[i % len(CARVANA_CROSS_COLORS)]
              for i, d in enumerate(carvana_prime)}
    cm_map = {d: CARMAX_COLORS[i % len(CARMAX_COLORS)]
              for i, d in enumerate(carmax_prime)}

    cv = _carvana_prime_traces(carvana_prime, cv_map)
    cm = _carmax_traces(carmax_prime, cm_map)

    # Merge each bucket — Carvana first so they render under CarMax
    merged = {k: cv.get(k, []) + cm.get(k, []) for k in ("pf", "cum_loss_age", "pf_loss", "spread", "dq", "co")}

    h = ('<p style="font-size:.75rem;color:#666;margin:8px 12px;">'
         "Every Carvana Prime deal (blue family) and every CarMax CARMX deal "
         "(orange/yellow family) on the same axes, indexed to deal age. "
         "Click a legend entry to hide/show that deal; double-click to isolate.</p>")

    def _plot(bucket, layout):
        if merged.get(bucket):
            return chart(merged[bucket], layout, height=500)
        return ""

    h += _plot("pf", {
        "title": "Carvana vs CarMax (Prime) — Pool Factor by Deal Age",
        "xaxis": {"title": "Deal Age (Months)"},
        "yaxis": {"tickformat": ".0%", "title": "Pool Factor (Remaining / Original)"},
        "hovermode": "closest", "legend": {"orientation": "h", "y": -0.4},
    })
    h += _plot("cum_loss_age", {
        "title": "Carvana vs CarMax (Prime) — Cumulative Net Loss Rate by Deal Age",
        "xaxis": {"title": "Deal Age (Months)"},
        "yaxis": {"tickformat": ".2%", "title": "Cum Net Loss (% of Orig Bal)"},
        "hovermode": "closest", "legend": {"orientation": "h", "y": -0.4},
    })
    h += _plot("pf_loss", {
        "title": "Carvana vs CarMax (Prime) — Cumulative Net Loss vs Pool Factor",
        "xaxis": {"title": "Pool Factor (Remaining / Original)",
                  "tickformat": ".0%", "autorange": "reversed"},
        "yaxis": {"tickformat": ".2%", "title": "Cum Net Loss (% of Orig Bal)"},
        "hovermode": "closest", "legend": {"orientation": "h", "y": -0.4},
    })
    h += _plot("dq", {
        "title": "Carvana vs CarMax (Prime) — Delinquency Rate by Deal Age",
        "xaxis": {"title": "Deal Age (Months)"},
        "yaxis": {"tickformat": ".2%", "title": "DQ Balance / Pool Balance"},
        "hovermode": "closest", "legend": {"orientation": "h", "y": -0.4},
    })
    h += _plot("co", {
        "title": "Carvana vs CarMax (Prime) — Annualized Net Charge-Off Rate by Deal Age",
        "xaxis": {"title": "Deal Age (Months)"},
        "yaxis": {"tickformat": ".2%",
                  "title": "Net Charge-Offs × 12 / Prior Month Balance"},
        "hovermode": "closest", "legend": {"orientation": "h", "y": -0.4},
    })
    h += _plot("spread", {
        "title": "Carvana vs CarMax (Prime) — Excess Spread by Deal Age",
        "xaxis": {"title": "Deal Age (Months)"},
        "yaxis": {"tickformat": ".2%", "title": "Consumer Rate − Trust Cost of Debt"},
        "hovermode": "closest", "legend": {"orientation": "h", "y": -0.4},
    })
    h += ('<p style="font-size:.7rem;color:#888;margin-top:12px;">'
          "Carvana DQ series here is cert-parsed 31–120 day buckets divided by ending pool balance. "
          "CarMax DQ series is total delinquent balance (31+ days) divided by ending pool balance. "
          "The two are slightly different definitions — CarMax includes a 121+ bucket; Carvana charges "
          "those loans off. Treat cross-issuer DQ comparisons with that caveat in mind.</p>")
    return h


def generate_deal_content(deal):
    """Generate all HTML content (metrics + tabs) for a single deal. Returns (metrics_html, tabs_content) or None."""
    global _chart_id

    ORIG_BAL = get_orig_bal(deal)
    lp = q("SELECT * FROM monthly_summary WHERE deal=? ORDER BY reporting_period_end", (deal,))
    if lp.empty:
        logger.warning(f"No monthly_summary data for {deal}, skipping.")
        return None
    lp["period"] = lp["reporting_period_end"].apply(nd)
    lp = lp.sort_values("period").reset_index(drop=True)

    pool = q("SELECT * FROM pool_performance WHERE deal=? ORDER BY dist_date_iso", (deal,))
    # Log data availability for debugging
    has_pool = not pool.empty
    has_wac_pp = has_pool and "weighted_avg_apr" in pool.columns and pool["weighted_avg_apr"].notna().any()
    has_wac_ms = "weighted_avg_coupon" in lp.columns and lp["weighted_avg_coupon"].notna().any()
    has_note_int = has_pool and "total_note_interest" in pool.columns and pool["total_note_interest"].notna().any()
    has_note_bal = has_pool and "aggregate_note_balance" in pool.columns and (pool["aggregate_note_balance"].fillna(0) > 0).any()
    logger.info(f"[{deal}] Data: pool_perf={has_pool}, wac_pp={has_wac_pp}, wac_ms={has_wac_ms}, "
                f"note_interest={has_note_int}, note_balance={has_note_bal}")
    if not pool.empty:
        pool["period"] = pool["distribution_date"].apply(nd)
        pool = pool.sort_values("period").reset_index(drop=True)

    # Cumulative columns
    lp["cum_co"] = lp["period_chargeoffs"].cumsum()
    lp["cum_rec"] = lp["period_recoveries"].cumsum()
    lp["cum_net"] = lp["cum_co"] - lp["cum_rec"]
    lp["loss_rate"] = lp["cum_net"] / ORIG_BAL
    lp["dq_rate"] = lp["total_dq_balance"] / lp["total_balance"]
    lp["dq30r"] = lp["dq_30_balance"] / lp["total_balance"]
    lp["dq60r"] = lp["dq_60_balance"] / lp["total_balance"]
    lp["dq90r"] = lp["dq_90_balance"] / lp["total_balance"]
    lp["dq120r"] = lp["dq_120_plus_balance"] / lp["total_balance"]
    lp["net_loss"] = lp["period_chargeoffs"] - lp["period_recoveries"]

    # For cash waterfall, we need pool_performance data to compute note paydowns
    # and estimate note interest. Without it, we can only show collections/losses.
    note_cols = ["note_balance_a1","note_balance_a2","note_balance_a3","note_balance_a4",
                 "note_balance_b","note_balance_c","note_balance_d","note_balance_n"]
    if not pool.empty:
        avail_notes = [c for c in note_cols if c in pool.columns]
        if avail_notes:
            pool["total_notes"] = pool[avail_notes].fillna(0).sum(axis=1)
            pool["note_principal_paid"] = -pool["total_notes"].diff().fillna(0)
            pool["note_principal_paid"] = pool["note_principal_paid"].clip(lower=0)
            # Estimate note interest: WAC of pool is ~8%, note WAC is roughly 1-2% for investment grade
            # Use a conservative estimate: total_notes * 0.02 / 12 (2% annual blended coupon)
            pool["est_note_interest"] = pool["total_notes"] * 0.02 / 12

    lp["cum_rec_rate"] = lp["cum_rec"] / lp["cum_co"].replace(0, float("nan"))

    x = lp["period"].tolist()
    last = lp.iloc[-1]
    sections = {}

    # ── POOL SUMMARY ──
    # Use compact y-axis labels ($100M instead of $100,000,000) and same x-axis for all 3 charts
    bal_in_millions = [round(v / 1e6, 1) for v in lp["total_balance"].tolist()]
    h = chart([{"x": x, "y": bal_in_millions, "type": "scatter", "fill": "tozeroy", "name": "Balance"}],
              {"title": "Remaining Pool Balance ($M)", "yaxis": {"ticksuffix": "M", "tickprefix": "$"}, "hovermode": "x unified"})
    h += chart([{"x": x, "y": [int(v) for v in lp["active_loans"].tolist()], "type": "scatter", "name": "Loans"}],
               {"title": "Active Loan Count", "hovermode": "x unified"})
    # ── Rate Curves: Collateral WAC and Cost of Debt ──
    # 1) Collateral WAC: prefer pool_performance, fall back to monthly_summary pre-computed WAC
    wac = pd.DataFrame()
    if not pool.empty and "weighted_avg_apr" in pool.columns:
        wac = pool.dropna(subset=["weighted_avg_apr"])[["period", "weighted_avg_apr"]].copy()
    if wac.empty and "weighted_avg_coupon" in lp.columns:
        wac_ms = lp.dropna(subset=["weighted_avg_coupon"])[["period", "weighted_avg_coupon"]].copy()
        if not wac_ms.empty:
            wac_ms = wac_ms.rename(columns={"weighted_avg_coupon": "weighted_avg_apr"})
            wac = wac_ms
    # Fallback: flat line from avg loan interest rate
    if wac.empty:
        avg_rate = q("SELECT AVG(original_interest_rate) as r FROM loans WHERE deal=? AND original_interest_rate IS NOT NULL", (deal,))
        if not avg_rate.empty and avg_rate.iloc[0]["r"]:
            flat_wac = float(avg_rate.iloc[0]["r"])
            wac = pd.DataFrame({"period": lp["period"], "weighted_avg_apr": flat_wac})
            logger.info(f"[{deal}] Using flat-line WAC from loan avg: {flat_wac:.4%}")
    # 2) Cost of Debt: weighted avg of note coupon rates × note balances
    cod = pd.DataFrame()
    try:
        notes_df = q("SELECT class, coupon_rate, original_balance FROM notes WHERE deal=? AND coupon_rate IS NOT NULL", (deal,))
    except Exception:
        try:
            notes_df = q("SELECT class, coupon_rate FROM notes WHERE deal=? AND coupon_rate IS NOT NULL", (deal,))
        except Exception:
            notes_df = pd.DataFrame()

    # Merged Method 1+2: use actual interest data when available, weighted coupon fallback per period
    m1_count = 0
    m2_count = 0
    if not pool.empty:
        # Build normalized rate lookup from notes for Method 2 fallback
        norm_rate_lookup = {}
        if not notes_df.empty:
            for cls, rate in zip(notes_df["class"], notes_df["coupon_rate"]):
                norm = cls.upper().replace("-", "").replace(" ", "").replace("CLASS", "")
                norm_rate_lookup[norm] = rate
        bal_cols = {"A1": "note_balance_a1", "A2": "note_balance_a2", "A3": "note_balance_a3",
                    "A4": "note_balance_a4", "B": "note_balance_b", "C": "note_balance_c",
                    "D": "note_balance_d", "N": "note_balance_n"}
        # Forward-fill note balance columns
        for col in bal_cols.values():
            if col in pool.columns:
                pool[col] = pool[col].ffill()

        has_ni_col = "total_note_interest" in pool.columns
        has_nb_col = "aggregate_note_balance" in pool.columns
        cod_rows = []
        filtered_count = 0
        for _, row in pool.iterrows():
            # Method 1: actual interest / actual balance (best)
            used_m1 = False
            if has_ni_col and has_nb_col:
                ni = row.get("total_note_interest")
                nb = row.get("aggregate_note_balance")
                if pd.notna(ni) and pd.notna(nb) and nb > 0 and ni > 0:
                    val = float(ni) / float(nb) * 12
                    if 0 < val < 0.25:
                        cod_rows.append({"period": row["period"], "cost_of_debt": val})
                        m1_count += 1
                        used_m1 = True
                    else:
                        logger.debug(f"  [{deal}] Period {row.get('period')}: CoD value {val:.4%} filtered (outside 0-25% range), ni={ni}, nb={nb}")
                        filtered_count += 1

            # Method 2 fallback: weighted coupon rates × note balances
            if not used_m1 and norm_rate_lookup:
                weighted_sum = 0.0
                total_bal = 0.0
                for cls, col in bal_cols.items():
                    if col in pool.columns and cls in norm_rate_lookup:
                        bal = row.get(col)
                        if pd.notna(bal) and float(bal) > 0:
                            weighted_sum += norm_rate_lookup[cls] * float(bal)
                            total_bal += float(bal)
                if total_bal > 0:
                    cod_rows.append({"period": row["period"], "cost_of_debt": weighted_sum / total_bal})
                    m2_count += 1

        if filtered_count > 0:
            logger.warning(f"[{deal}] Filtered {filtered_count} CoD values outside (0, 25%) range")
        if cod_rows:
            cod = pd.DataFrame(cod_rows)
            logger.info(f"[{deal}] Merged CoD: {m1_count} periods from actual interest, {m2_count} from weighted coupons")

    # Method 3: flat line from notes table — works even if pool_performance is empty
    if len(cod) < 3 and not notes_df.empty:
        flat_rate = None
        if "original_balance" in notes_df.columns and notes_df["original_balance"].notna().any():
            ob = notes_df["original_balance"].fillna(0)
            if ob.sum() > 0:
                flat_rate = float((notes_df["coupon_rate"] * ob).sum() / ob.sum())
        if flat_rate is None:
            flat_rate = float(notes_df["coupon_rate"].mean())
        if flat_rate and flat_rate > 0:
            # Use monthly_summary periods if pool_performance is empty
            periods = pool["period"] if not pool.empty else lp["period"]
            cod = pd.DataFrame({"period": periods, "cost_of_debt": flat_rate})
            logger.info(f"[{deal}] Using flat-line CoD from notes: {flat_rate:.4%}")

    # Method 4 (rough estimate): derive from avg loan interest rate if nothing else works
    if len(cod) < 3:
        avg_rate_q = q("SELECT AVG(original_interest_rate) as r FROM loans WHERE deal=? AND original_interest_rate IS NOT NULL", (deal,))
        if not avg_rate_q.empty and avg_rate_q.iloc[0]["r"]:
            avg_loan_rate = float(avg_rate_q.iloc[0]["r"])
            rough_cod = avg_loan_rate * 0.4  # rough proxy: funding cost ~ 40% of loan yield
            periods = pool["period"] if not pool.empty else lp["period"]
            cod = pd.DataFrame({"period": periods, "cost_of_debt": rough_cod})
            logger.info(f"[{deal}] Using rough CoD estimate from loan avg rate ({avg_loan_rate:.4%} * 0.4 = {rough_cod:.4%})")

    # 3) Render separate charts for consumer rate and cost of debt
    if not wac.empty:
        h += chart([{"x": wac["period"].tolist(), "y": wac["weighted_avg_apr"].tolist(),
                     "type": "scatter", "line": {"color": "#1976D2"}}],
                   {"title": "Avg Consumer Rate", "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified",
                    "xaxis": {"range": [x[0], x[-1]], "tickangle": -45, "automargin": True}})
    else:
        logger.warning(f"[{deal}] No consumer rate (WAC) data available")
    if not cod.empty:
        cod_min, cod_max = cod["cost_of_debt"].min(), cod["cost_of_debt"].max()
        logger.info(f"[{deal}] CoD range: {cod_min:.4%} - {cod_max:.4%} (n={len(cod)})")
        h += chart([{"x": cod["period"].tolist(), "y": cod["cost_of_debt"].tolist(),
                     "type": "scatter", "line": {"color": "#D32F2F"}}],
                   {"title": "Avg Trust Cost of Debt", "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified",
                    "xaxis": {"range": [x[0], x[-1]], "tickangle": -45, "automargin": True}})
    else:
        logger.warning(f"[{deal}] No cost of debt data available")
    sections["Pool Summary"] = h

    # ── DELINQUENCIES ──
    # Tail-amortization mask (audit #9): once pool drops below 10% of original
    # balance, remaining-balance denominator becomes noisy and the rate is
    # meaningless. Mask rate traces there; keep raw dollar balances visible.
    _tail_mask = [(b / ORIG_BAL) < 0.10 if (b and ORIG_BAL) else False
                  for b in lp["total_balance"].tolist()]
    def _mask_tail(series):
        return [None if m else v for v, m in zip(series, _tail_mask)]
    h = chart([
        {"x": x, "y": _mask_tail(lp["dq30r"].tolist()), "name": "30d", "stackgroup": "dq", "line": {"color": "#FFC107"}},
        {"x": x, "y": _mask_tail(lp["dq60r"].tolist()), "name": "60d", "stackgroup": "dq", "line": {"color": "#FF9800"}},
        {"x": x, "y": _mask_tail(lp["dq90r"].tolist()), "name": "90d", "stackgroup": "dq", "line": {"color": "#FF5722"}},
        {"x": x, "y": _mask_tail(lp["dq120r"].tolist()), "name": "120+d", "stackgroup": "dq", "line": {"color": "#D32F2F"}},
    ], {"title": "Delinquency Rates (% of Pool)", "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified"})
    if any(_tail_mask):
        # Raw dollar-balance stacked area stays visible for the tail.
        h += chart([
            {"x": x, "y": lp["dq_30_balance"].tolist(), "name": "30d", "stackgroup": "dq", "line": {"color": "#FFC107"}},
            {"x": x, "y": lp["dq_60_balance"].tolist(), "name": "60d", "stackgroup": "dq", "line": {"color": "#FF9800"}},
            {"x": x, "y": lp["dq_90_balance"].tolist(), "name": "90d", "stackgroup": "dq", "line": {"color": "#FF5722"}},
            {"x": x, "y": lp["dq_120_plus_balance"].tolist(), "name": "120+d", "stackgroup": "dq", "line": {"color": "#D32F2F"}},
        ], {"title": "Delinquency Balances ($) — pool &lt; 10% of original",
            "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})
        h += ('<p style="font-size:.75rem;color:#666;margin-top:-4px;">'
              "Rate trace is suppressed once the pool amortizes below 10% of "
              "its original balance — at that point the rate denominator is "
              "too small to be meaningful. Raw dollar balances remain visible."
              "</p>")
    if not pool.empty and "delinquency_trigger_level" in pool.columns:
        trig = pool.dropna(subset=["delinquency_trigger_level", "delinquency_trigger_actual"])
        if not trig.empty:
            h += chart([
                {"x": trig["period"].tolist(), "y": trig["delinquency_trigger_level"].tolist(), "name": "Trigger", "line": {"dash": "dash", "color": "red"}},
                {"x": trig["period"].tolist(), "y": trig["delinquency_trigger_actual"].tolist(), "name": "Actual", "line": {"color": "blue"}},
            ], {"title": "60+ DQ vs Trigger Level", "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified"})
    dq_tbl = pd.DataFrame({
        "Bucket": ["30d","60d","90d","120+d","Total"],
        "Count": [int(last["dq_30_count"]),int(last["dq_60_count"]),int(last["dq_90_count"]),int(last["dq_120_plus_count"]),int(last["total_dq_count"])],
        "Balance": [fm(last["dq_30_balance"]),fm(last["dq_60_balance"]),fm(last["dq_90_balance"]),fm(last["dq_120_plus_balance"]),fm(last["total_dq_balance"])],
        "% Pool": [f"{last['dq30r']:.2%}",f"{last['dq60r']:.2%}",f"{last['dq90r']:.2%}",f"{last['dq120r']:.2%}",f"{last['dq_rate']:.2%}"],
    })
    h += "<h3>Latest Period</h3>" + table_html(dq_tbl)
    sections["Delinquencies"] = h

    # ── LOSSES ──
    h = chart([{"x": x, "y": lp["loss_rate"].tolist(), "type": "scatter", "fill": "tozeroy", "line": {"color": "#D32F2F"}}],
              {"title": f"Cumulative Net Loss Rate (% of {fm(ORIG_BAL)})", "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified"})
    # Restatement overlay (audit #7) — applies to cum_net (derived from cumsum
    # of period chargeoffs/recoveries for Carvana). Restatements show up when
    # the servicer adjusts period flows downward in a later cert.
    _net_traces = [
        {"x": x, "y": lp["cum_co"].tolist(), "name": "Gross Chargeoffs", "line": {"color": "#D32F2F"}},
        {"x": x, "y": lp["cum_rec"].tolist(), "name": "Recoveries", "line": {"color": "#4CAF50"}},
        {"x": x, "y": lp["cum_net"].tolist(), "name": "Net Losses", "line": {"color": "#FF9800", "dash": "dash"}},
    ]
    _env, _mx, _my = _restatement_overlay(x, lp["cum_net"].tolist())
    if _env is not None:
        _net_traces.append({"x": x, "y": _env, "name": "Net Losses (monotone envelope)",
                            "line": {"color": "#FF9800", "dash": "dot", "width": 1},
                            "opacity": 0.5})
    if _mx:
        _net_traces.append({
            "x": _mx, "y": _my, "name": "Restatement",
            "mode": "markers", "type": "scatter",
            "marker": {"symbol": "triangle-down", "size": 9, "color": "#607D8B"},
            "hovertemplate": "Servicer restated cumulative loss on %{x}<extra></extra>",
        })
    h += chart(_net_traces, {"title": "Cumulative Gross Losses vs Recoveries", "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})
    rr = lp.dropna(subset=["cum_rec_rate"])
    if not rr.empty:
        h += chart([{"x": rr["period"].tolist(), "y": rr["cum_rec_rate"].tolist(), "line": {"color": "#4CAF50"}}],
                   {"title": "Cumulative Recovery Rate", "yaxis": {"tickformat": ".1%"}, "hovermode": "x unified"})
    h += chart([
        {"x": x, "y": lp["period_chargeoffs"].tolist(), "name": "Chargeoffs", "type": "bar", "marker": {"color": "#D32F2F"}},
        {"x": x, "y": lp["period_recoveries"].tolist(), "name": "Recoveries", "type": "bar", "marker": {"color": "#4CAF50"}},
    ], {"title": "Monthly Chargeoffs vs Recoveries", "barmode": "group", "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})

    # Loss by credit score
    lbs = q("""SELECT l.obligor_credit_score as segment, COUNT(*) as lc, SUM(l.original_loan_amount) as ob,
               SUM(COALESCE(s.total_chargeoff,0)) as co, SUM(COALESCE(s.total_recovery,0)) as rec
            FROM loans l LEFT JOIN loan_loss_summary s ON l.deal=s.deal AND l.asset_number=s.asset_number
            WHERE l.deal=? AND l.obligor_credit_score IS NOT NULL GROUP BY l.obligor_credit_score""", (deal,))
    if not lbs.empty:
        lbs["bkt"] = pd.cut(lbs["segment"], bins=[0,580,620,660,700,740,780,820,900],
                            labels=["<580","580-619","620-659","660-699","700-739","740-779","780-819","820+"], right=False)
        b = lbs.groupby("bkt",observed=True).agg({"lc":"sum","ob":"sum","co":"sum","rec":"sum"}).reset_index()
        b["net"] = b["co"] - b["rec"]; b["rate"] = b["net"] / b["ob"]
        d = pd.DataFrame({"Score":b["bkt"],"Loans":b["lc"].apply(lambda x:f"{x:,}"),
            "Orig Bal":b["ob"].apply(fm),"Net Loss":b["net"].apply(fm),"Loss Rate":b["rate"].apply(lambda x:f"{x:.2%}")})
        h += "<h3>Losses by Credit Score</h3>" + table_html(d)

    # Loss by rate
    lbr = q("""SELECT l.original_interest_rate as segment, COUNT(*) as lc, SUM(l.original_loan_amount) as ob,
               SUM(COALESCE(s.total_chargeoff,0)) as co, SUM(COALESCE(s.total_recovery,0)) as rec
            FROM loans l LEFT JOIN loan_loss_summary s ON l.deal=s.deal AND l.asset_number=s.asset_number
            WHERE l.deal=? AND l.original_interest_rate IS NOT NULL GROUP BY l.original_interest_rate""", (deal,))
    if not lbr.empty:
        lbr["bkt"] = pd.cut(lbr["segment"], bins=[0,0.04,0.06,0.08,0.10,0.12,0.15,0.20,1.0],
                            labels=["<4%","4-5.99%","6-7.99%","8-9.99%","10-11.99%","12-14.99%","15-19.99%","20%+"], right=False)
        b = lbr.groupby("bkt",observed=True).agg({"lc":"sum","ob":"sum","co":"sum","rec":"sum"}).reset_index()
        b["net"] = b["co"] - b["rec"]; b["rate"] = b["net"] / b["ob"]
        d = pd.DataFrame({"Rate":b["bkt"],"Loans":b["lc"].apply(lambda x:f"{x:,}"),
            "Orig Bal":b["ob"].apply(fm),"Net Loss":b["net"].apply(fm),"Loss Rate":b["rate"].apply(lambda x:f"{x:.2%}")})
        h += "<h3>Losses by Interest Rate</h3>" + table_html(d)
    sections["Losses"] = h

    # ── CASH WATERFALL ──
    h = ""

    # Collections table from loan-level data
    wf = lp[["period","interest_collected","principal_collected","period_recoveries",
             "est_servicing_fee","period_chargeoffs","net_loss"]].copy()
    wf.columns = ["Period","Interest","Principal","Recoveries","Svc Fee","Chargeoffs","Net Loss"]
    sums = wf.select_dtypes(include="number").sum()
    sr = pd.DataFrame([["TOTAL"]+sums.tolist()], columns=wf.columns)
    wf_all = pd.concat([wf, sr], ignore_index=True)
    wf_fmt = wf_all.copy()
    for c in wf_fmt.columns[1:]:
        wf_fmt[c] = wf_all[c].apply(lambda x: fm(x) if pd.notna(x) else "")
    h += "<h3>Monthly Collections & Losses</h3>" + table_html(wf_fmt)

    # Cumulative cash flow chart
    cum_int = lp["interest_collected"].cumsum()
    cum_prin = lp["principal_collected"].cumsum()
    cum_svc = lp["est_servicing_fee"].cumsum()
    h += chart([
        {"x": x, "y": cum_int.tolist(), "name": "Cum Interest", "line": {"color": "#1976D2"}},
        {"x": x, "y": cum_prin.tolist(), "name": "Cum Principal", "line": {"color": "#388E3C"}},
        {"x": x, "y": lp["cum_co"].tolist(), "name": "Cum Chargeoffs", "line": {"color": "#D32F2F"}},
        {"x": x, "y": lp["cum_rec"].tolist(), "name": "Cum Recoveries", "line": {"color": "#4CAF50"}},
        {"x": x, "y": cum_svc.tolist(), "name": "Cum Servicing Fee", "line": {"color": "#FF9800", "dash": "dash"}},
    ], {"title": "Cumulative Cash Flows", "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})

    # Actual waterfall from servicer certificate (where available)
    if not pool.empty and "residual_cash" in pool.columns and pool["residual_cash"].notna().any():
        pool_x = pool["period"].tolist()
        h += "<h3>Cash Waterfall (from Servicer Certificate)</h3>"

        # Build waterfall table with actual filing data
        wf_cols = ["period"]
        wf_names = ["Period"]
        for col, name in [("total_deposited", "Total Deposited"), ("available_funds", "Available Funds"),
                          ("actual_servicing_fee", "Servicing Fee"), ("total_note_interest", "Note Interest"),
                          ("regular_pda", "Principal Dist"), ("residual_cash", "Residual (to Equity)")]:
            if col in pool.columns and pool[col].notna().any():
                wf_cols.append(col)
                wf_names.append(name)
        if len(wf_cols) > 1:
            wf_pool = pool[wf_cols].copy()
            wf_pool.columns = wf_names
            # Add totals row
            sums_p = wf_pool.select_dtypes(include="number").sum()
            sr_p = pd.DataFrame([["TOTAL"] + sums_p.tolist()], columns=wf_pool.columns)
            wf_pool_all = pd.concat([wf_pool, sr_p], ignore_index=True)
            wf_pool_fmt = wf_pool_all.copy()
            for c in wf_pool_fmt.columns[1:]:
                wf_pool_fmt[c] = wf_pool_all[c].apply(lambda x: fm(x) if pd.notna(x) and x != 0 else "-")
            h += table_html(wf_pool_fmt)

        # Residual cash chart
        res_data = pool[pool["residual_cash"].notna()]
        if not res_data.empty:
            cum_res = res_data["residual_cash"].cumsum()
            cum_res_pct = cum_res / ORIG_BAL
            h += chart([{"x": res_data["period"].tolist(), "y": cum_res_pct.tolist(),
                         "type": "scatter", "fill": "tozeroy", "line": {"color": "#388E3C"}}],
                       {"title": "Cumulative Cash to Residual (% of Original Balance)",
                        "yaxis": {"tickformat": ".2%"}, "hovermode": "x unified"})

    # Debt table from pool_performance (where available)
    if not pool.empty and "total_notes" in pool.columns:
        pool_x = pool["period"].tolist()
        h += "<h3>Debt & Equity (from Servicer Certificate)</h3>"

        # Build debt paydown table
        debt_cols = ["period"]
        debt_names = ["Period"]
        for nc in note_cols:
            if nc in pool.columns and pool[nc].notna().any():
                debt_cols.append(nc)
                debt_names.append(nc.replace("note_balance_","").upper())
        if "total_notes" in pool.columns:
            debt_cols.append("total_notes")
            debt_names.append("Total Debt")
        if "overcollateralization_amount" in pool.columns:
            debt_cols.append("overcollateralization_amount")
            debt_names.append("OC")
        if "reserve_account_balance" in pool.columns:
            debt_cols.append("reserve_account_balance")
            debt_names.append("Reserve")
        dt = pool[debt_cols].copy()
        dt.columns = debt_names
        dt_fmt = dt.copy()
        for c in dt_fmt.columns[1:]:
            dt_fmt[c] = dt[c].apply(lambda x: fm(x) if pd.notna(x) and x != 0 else "-")
        h += table_html(dt_fmt)

        # Debt paydown chart
        h += chart([
            {"x": pool_x, "y": pool["total_notes"].tolist(), "name": "Total Debt", "fill": "tozeroy", "line": {"color": "#7B1FA2"}},
        ], {"title": "Outstanding Debt Over Time", "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})

    sections["Cash Waterfall"] = h

    # ── RECOVERY ──
    rec = q("""SELECT s.asset_number, s.chargeoff_period, s.total_chargeoff,
               s.first_recovery_period, s.total_recovery, l.obligor_credit_score
            FROM loan_loss_summary s LEFT JOIN loans l ON s.deal=l.deal AND s.asset_number=l.asset_number
            WHERE s.deal=? AND s.total_chargeoff > 0""", (deal,))
    h = ""
    if not rec.empty:
        from datetime import datetime as dt
        def pd_dt(d):
            if not d: return None
            for f in ["%m-%d-%Y","%m/%d/%Y","%Y-%m-%d"]:
                try: return dt.strptime(str(d).strip(),f)
                except: continue
            return None
        rec["co_dt"] = rec["chargeoff_period"].apply(pd_dt)
        rec["rec_dt"] = rec["first_recovery_period"].apply(pd_dt)
        rec["has_rec"] = rec["total_recovery"].notna() & (rec["total_recovery"] > 0)
        rec["months"] = rec.apply(lambda r: ((r["rec_dt"].year-r["co_dt"].year)*12+r["rec_dt"].month-r["co_dt"].month) if pd.notna(r["rec_dt"]) and pd.notna(r["co_dt"]) else None, axis=1)
        tc=len(rec); wr=int(rec["has_rec"].sum())
        ar=rec.loc[rec["has_rec"],"total_recovery"].sum()/rec["total_chargeoff"].sum() if rec["total_chargeoff"].sum()>0 else 0
        mm=rec.loc[rec["has_rec"],"months"].median()
        tca=rec["total_chargeoff"].sum(); tra=rec.loc[rec["has_rec"],"total_recovery"].sum()
        h += f'<div class="metrics"><div class="metric"><div class="mv">{tc:,}</div><div class="ml">Charged-Off Loans</div></div>'
        h += f'<div class="metric"><div class="mv">{wr:,} ({wr/tc:.0%})</div><div class="ml">With Recovery</div></div>'
        h += f'<div class="metric"><div class="mv">{ar:.1%}</div><div class="ml">Recovery Rate</div></div>'
        h += f'<div class="metric"><div class="mv">{mm:.0f}mo</div><div class="ml">Median Time</div></div>'
        h += f'<div class="metric"><div class="mv">{fm(tca)}</div><div class="ml">Total Chargeoffs</div></div>'
        h += f'<div class="metric"><div class="mv">{fm(tra)}</div><div class="ml">Total Recovered</div></div></div>'
        rw = rec[rec["has_rec"] & rec["months"].notna()]
        if not rw.empty:
            import numpy as np
            counts, edges = np.histogram(rw["months"].values, bins=30)
            centers = [(edges[i]+edges[i+1])/2 for i in range(len(counts))]
            h += chart([{"x": centers, "y": counts.tolist(), "type": "bar", "marker": {"color": "#1976D2"}}],
                       {"title": "Months to First Recovery", "hovermode": "x unified"})

        # Recovery rate by credit score
        rec_fico = rec[rec["obligor_credit_score"].notna()].copy()
        if not rec_fico.empty:
            rec_fico["bkt"] = pd.cut(rec_fico["obligor_credit_score"],
                bins=[0,580,620,660,700,740,780,820,900],
                labels=["<580","580-619","620-659","660-699","700-739","740-779","780-819","820+"], right=False)
            b = rec_fico.groupby("bkt", observed=True).agg(
                loans=("asset_number","count"),
                chargeoffs=("total_chargeoff","sum"),
                recoveries=("total_recovery", lambda x: x.fillna(0).sum()),
            ).reset_index()
            b["rec_rate"] = b["recoveries"] / b["chargeoffs"].replace(0, float("nan"))
            # Bar chart
            h += chart([
                {"x": b["bkt"].tolist(), "y": [round(v,4) if pd.notna(v) else 0 for v in b["rec_rate"]], "type": "bar", "marker": {"color": "#4CAF50"}},
            ], {"title": "Recovery Rate by Credit Score", "yaxis": {"tickformat": ".1%"}, "hovermode": "x unified"})
            # Table
            tbl = pd.DataFrame({
                "Score": b["bkt"],
                "Charged-Off Loans": b["loans"].apply(lambda x: f"{x:,}"),
                "Total Chargeoffs": b["chargeoffs"].apply(fm),
                "Total Recovered": b["recoveries"].apply(fm),
                "Recovery Rate": b["rec_rate"].apply(lambda x: f"{x:.1%}" if pd.notna(x) else "-"),
            })
            h += table_html(tbl)

        # Recovery rate by interest rate
        rec_rate_data = q("""SELECT s.asset_number, s.total_chargeoff, s.total_recovery,
                             l.original_interest_rate
                          FROM loan_loss_summary s
                          LEFT JOIN loans l ON s.deal=l.deal AND s.asset_number=l.asset_number
                          WHERE s.deal=? AND s.total_chargeoff > 0
                          AND l.original_interest_rate IS NOT NULL""", (deal,))
        if not rec_rate_data.empty:
            rec_rate_data["bkt"] = pd.cut(rec_rate_data["original_interest_rate"],
                bins=[0,0.04,0.06,0.08,0.10,0.12,0.15,0.20,1.0],
                labels=["<4%","4-5.99%","6-7.99%","8-9.99%","10-11.99%","12-14.99%","15-19.99%","20%+"], right=False)
            b = rec_rate_data.groupby("bkt", observed=True).agg(
                loans=("asset_number","count"),
                chargeoffs=("total_chargeoff","sum"),
                recoveries=("total_recovery", lambda x: x.fillna(0).sum()),
            ).reset_index()
            b["rec_rate"] = b["recoveries"] / b["chargeoffs"].replace(0, float("nan"))
            h += chart([
                {"x": b["bkt"].tolist(), "y": [round(v,4) if pd.notna(v) else 0 for v in b["rec_rate"]], "type": "bar", "marker": {"color": "#388E3C"}},
            ], {"title": "Recovery Rate by Interest Rate", "yaxis": {"tickformat": ".1%"}, "hovermode": "x unified"})
            tbl = pd.DataFrame({
                "Rate": b["bkt"],
                "Charged-Off Loans": b["loans"].apply(lambda x: f"{x:,}"),
                "Total Chargeoffs": b["chargeoffs"].apply(fm),
                "Total Recovered": b["recoveries"].apply(fm),
                "Recovery Rate": b["rec_rate"].apply(lambda x: f"{x:.1%}" if pd.notna(x) else "-"),
            })
            h += table_html(tbl)
    sections["Recovery"] = h

    # ── NOTES & OC ──
    h = ""
    if not pool.empty:
        nc = [c for c in ["note_balance_a1","note_balance_a2","note_balance_a3","note_balance_a4",
                           "note_balance_b","note_balance_c","note_balance_d","note_balance_n"]
              if c in pool.columns and pool[c].notna().any()]
        if nc:
            traces = []
            for c in nc:
                traces.append({"x": pool["period"].tolist(), "y": pool[c].fillna(0).tolist(),
                               "name": c.replace("note_balance_","").upper(), "stackgroup": "notes"})
            h += chart(traces, {"title": "Note Balances", "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})
        oc = pool.dropna(subset=["overcollateralization_amount"], how="all")
        if not oc.empty:
            traces = []
            if "overcollateralization_amount" in oc.columns and oc["overcollateralization_amount"].notna().any():
                traces.append({"x": oc["period"].tolist(), "y": oc["overcollateralization_amount"].tolist(), "name": "OC"})
            if "reserve_account_balance" in oc.columns and oc["reserve_account_balance"].notna().any():
                traces.append({"x": oc["period"].tolist(), "y": oc["reserve_account_balance"].tolist(), "name": "Reserve"})
            if traces:
                h += chart(traces, {"title": "OC & Reserve Account", "yaxis": {"tickformat": "$,.0f"}, "hovermode": "x unified"})
    sections["Notes & OC"] = h

    # ── DOCUMENTS ──
    h = ""
    try:
        # Query servicer certificates from filings table
        certs = q("SELECT filing_date, servicer_cert_url, accession_number FROM filings "
                  "WHERE deal=? AND servicer_cert_url IS NOT NULL ORDER BY filing_date DESC", (deal,))
        if not certs.empty:
            h += "<h3>Servicer Certificates</h3>"
            cert_rows = []
            for _, cert_row in certs.iterrows():
                fd = cert_row["filing_date"]
                cert_url = cert_row["servicer_cert_url"]
                try:
                    dt_obj = datetime.strptime(str(fd).strip()[:10], "%Y-%m-%d")
                    date_display = dt_obj.strftime("%b %Y")
                    date_slug = dt_obj.strftime("%Y-%m")
                except (ValueError, TypeError):
                    date_display = str(fd)[:10] if fd else "Unknown"
                    date_slug = str(fd)[:7] if fd else "unknown"
                # Link directly to SEC EDGAR. We used to try serving locally
                # generated PDFs (docs/<deal>/<file>.pdf), but EDGAR servicer
                # certificates are image-based — the body is a set of JPG page
                # scans referenced by relative URL with a hidden OCR text layer.
                # Rendering that HTML with weasyprint produced a PDF containing
                # only the hidden text + document header (looked like a bare
                # exhibit reference with no real content). SEC serves the JPGs
                # in place, so the canonical EDGAR URL renders correctly.
                link = f'<a href="{cert_url}" target="_blank" rel="noopener">SEC&nbsp;Filing</a>'
                cert_rows.append({"Date": date_display, "Download": link})
            cert_df = pd.DataFrame(cert_rows)
            h += table_html(cert_df, cls="compare")
    except Exception as e:
        logger.warning(f"[{deal}] Error building servicer cert links: {e}")

    # Prospectus & Annual Reports — link to SEC EDGAR search for the deal's CIK
    try:
        from carvana_abs.config import DEALS as DEAL_REGISTRY
        deal_info = DEAL_REGISTRY.get(deal, {})
        cik = deal_info.get("cik", "")
        entity = deal_info.get("entity_name", f"Carvana Auto Receivables Trust {deal}")
        if cik:
            h += "<h3>Prospectus &amp; Other Filings</h3>"
            edgar_base = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
            filing_links = [
                {"Document": "All SEC Filings",
                 "Description": f"Complete filing history for {entity}",
                 "Link": f'<a href="{edgar_base}&type=&dateb=&owner=include&count=40" target="_blank" rel="noopener">EDGAR</a>'},
                {"Document": "Prospectus (424B)",
                 "Description": "Offering prospectus and supplements",
                 "Link": f'<a href="{edgar_base}&type=424B&dateb=&owner=include&count=10" target="_blank" rel="noopener">EDGAR</a>'},
                {"Document": "Annual Reports (10-K)",
                 "Description": "Annual reports filed with SEC",
                 "Link": f'<a href="{edgar_base}&type=10-K&dateb=&owner=include&count=10" target="_blank" rel="noopener">EDGAR</a>'},
                {"Document": "Current Reports (8-K)",
                 "Description": "Material event disclosures",
                 "Link": f'<a href="{edgar_base}&type=8-K&dateb=&owner=include&count=10" target="_blank" rel="noopener">EDGAR</a>'},
            ]
            h += table_html(pd.DataFrame(filing_links), cls="compare")
    except Exception as e:
        logger.warning(f"[{deal}] Error building prospectus links: {e}")

    if not h:
        h = "<p>No documents available for this deal.</p>"
    sections["Documents"] = h

    # Build metrics + tabs HTML for this deal.
    # Prefer the latest servicer cert for cum net loss rate (authoritative).
    # 30+ DQ rate uses the cert's 31-60 + 61-90 + 91-120 bucket sum / pool
    # balance, not monthly_summary which carries pre-charge-off loans in a
    # dq_120_plus bucket that the cert doesn't report.
    cert_cum_loss = get_cum_net_loss_rate(deal, ORIG_BAL)
    cum_loss_display = (f"{cert_cum_loss:.2%}" if cert_cum_loss is not None
                        else f"{last['loss_rate']:.2%}")
    dq_series = _cert_dq_series(deal)
    if dq_series:
        _, dq_last, epb_last = dq_series[-1]
        dq_display = f"{dq_last / epb_last:.2%}" if epb_last else f"{last['dq_rate']:.2%}"
    else:
        dq_display = f"{last['dq_rate']:.2%}"
    metrics_html = f"""<div class="metrics">
<div class="metric"><div class="mv">{fm(ORIG_BAL)}</div><div class="ml">Original Balance</div></div>
<div class="metric"><div class="mv">{fm(last['total_balance'])}</div><div class="ml">Current Balance</div></div>
<div class="metric"><div class="mv">{last['total_balance']/ORIG_BAL:.1%}</div><div class="ml">Pool Factor</div></div>
<div class="metric"><div class="mv">{int(last['active_loans']):,}</div><div class="ml">Active Loans</div></div>
<div class="metric"><div class="mv">{cum_loss_display}</div><div class="ml">Cum Loss Rate</div></div>
<div class="metric"><div class="mv">{dq_display}</div><div class="ml">30+ DQ Rate</div></div>
</div>"""

    # Build tab buttons and content
    deal_safe = deal.replace("-","_")
    tabs_html = ""; content_html = ""; first = True
    for name, body in sections.items():
        tid = f"{deal_safe}_{name.replace(' ','_').replace('&','and')}"
        tabs_html += f'<button class="tab{" active" if first else ""}" onclick="showTab(\'{tid}\',this)">{name}</button>\n'
        content_html += f'<div id="{tid}" class="tc" style="display:{"block" if first else "none"}">{body}</div>\n'
        first = False

    return metrics_html, f'<div class="tabs">{tabs_html}</div>\n{content_html}'


def generate_comparison_content(deals, title):
    """Generate comparison HTML (summary table + loss curve) for a group of deals."""
    h = ""

    # ── Summary Table ──
    rows = []
    for deal in deals:
        loan_stats = q("SELECT AVG(original_interest_rate) as avg_yield, AVG(obligor_credit_score) as avg_fico FROM loans WHERE deal=?", (deal,))
        avg_fico = loan_stats.iloc[0]["avg_fico"] if not loan_stats.empty and loan_stats.iloc[0]["avg_fico"] else None
        init_bal = get_orig_bal(deal)

        # ── Collateral WAC (init + current) ──
        # Prefer pool_performance.weighted_avg_apr, fall back to monthly_summary.weighted_avg_coupon
        init_wac = None
        curr_wac = None
        # Use dist_date_iso (YYYY-MM-DD) — distribution_date is M/D/YYYY text
        # and sorts lexicographically, not chronologically (audit finding #5).
        first_wac = q("SELECT weighted_avg_apr FROM pool_performance WHERE deal=? AND weighted_avg_apr IS NOT NULL ORDER BY dist_date_iso LIMIT 1", (deal,))
        last_wac = q("SELECT weighted_avg_apr FROM pool_performance WHERE deal=? AND weighted_avg_apr IS NOT NULL ORDER BY dist_date_iso DESC LIMIT 1", (deal,))
        if not first_wac.empty and first_wac.iloc[0]["weighted_avg_apr"]:
            init_wac = first_wac.iloc[0]["weighted_avg_apr"]
        if not last_wac.empty and last_wac.iloc[0]["weighted_avg_apr"]:
            curr_wac = last_wac.iloc[0]["weighted_avg_apr"]
        # monthly_summary fallback (pre-computed from loan-level data)
        if init_wac is None or curr_wac is None:
            wac_ms = q("SELECT weighted_avg_coupon FROM monthly_summary WHERE deal=? AND weighted_avg_coupon IS NOT NULL ORDER BY reporting_period_end", (deal,))
            if not wac_ms.empty:
                if init_wac is None and wac_ms.iloc[0]["weighted_avg_coupon"]:
                    init_wac = wac_ms.iloc[0]["weighted_avg_coupon"]
                if curr_wac is None and wac_ms.iloc[-1]["weighted_avg_coupon"]:
                    curr_wac = wac_ms.iloc[-1]["weighted_avg_coupon"]
        # Last resort: avg loan interest rate
        if init_wac is None or curr_wac is None:
            avg_rate = q("SELECT AVG(original_interest_rate) as r FROM loans WHERE deal=? AND original_interest_rate IS NOT NULL", (deal,))
            if not avg_rate.empty and avg_rate.iloc[0]["r"]:
                flat = float(avg_rate.iloc[0]["r"])
                if init_wac is None:
                    init_wac = flat
                if curr_wac is None:
                    curr_wac = flat

        # ── Cost of Debt: compute full time series, take first/last ──
        init_cod = None
        curr_cod = None
        try:
            notes_df = q("SELECT class, coupon_rate FROM notes WHERE deal=? AND coupon_rate IS NOT NULL", (deal,))
        except Exception:
            notes_df = pd.DataFrame()

        # Build full CoD time series (same merged Method 1+2 as per-deal chart)
        pool_all = q("SELECT * FROM pool_performance WHERE deal=? ORDER BY dist_date_iso", (deal,))
        if not pool_all.empty:
            norm_rate_lookup = {}
            if not notes_df.empty:
                for cls, rate in zip(notes_df["class"], notes_df["coupon_rate"]):
                    norm = cls.upper().replace("-", "").replace(" ", "").replace("CLASS", "")
                    norm_rate_lookup[norm] = rate
            bal_cols = {"A1": "note_balance_a1", "A2": "note_balance_a2", "A3": "note_balance_a3",
                        "A4": "note_balance_a4", "B": "note_balance_b", "C": "note_balance_c",
                        "D": "note_balance_d", "N": "note_balance_n"}
            for col in bal_cols.values():
                if col in pool_all.columns:
                    pool_all[col] = pool_all[col].ffill()
            has_ni = "total_note_interest" in pool_all.columns
            has_nb = "aggregate_note_balance" in pool_all.columns
            cod_series = []
            for _, row in pool_all.iterrows():
                # Method 1: actual interest ratio
                if has_ni and has_nb:
                    ni = row.get("total_note_interest")
                    nb = row.get("aggregate_note_balance")
                    if pd.notna(ni) and pd.notna(nb) and float(nb) > 0 and float(ni) > 0:
                        val = float(ni) / float(nb) * 12
                        if 0 < val < 0.25:
                            cod_series.append(val)
                            continue
                # Method 2: weighted coupon × balance
                if norm_rate_lookup:
                    w_sum, t_bal = 0.0, 0.0
                    for cls, col in bal_cols.items():
                        if col in pool_all.columns and cls in norm_rate_lookup:
                            bal = row.get(col)
                            if pd.notna(bal) and float(bal) > 0:
                                w_sum += norm_rate_lookup[cls] * float(bal)
                                t_bal += float(bal)
                    if t_bal > 0:
                        cod_series.append(w_sum / t_bal)
                        continue
                cod_series.append(None)

            # Take first and last non-None values
            valid = [(i, v) for i, v in enumerate(cod_series) if v is not None]
            if valid:
                init_cod = valid[0][1]
                curr_cod = valid[-1][1]
                logger.info(f"  [{deal}] Summary CoD from time series: init={init_cod:.4%}, curr={curr_cod:.4%} ({len(valid)} points)")

        # Fallback: flat rate from notes table
        if init_cod is None or curr_cod is None:
            if not notes_df.empty:
                try:
                    notes_ob = q("SELECT class, coupon_rate, original_balance FROM notes WHERE deal=? AND coupon_rate IS NOT NULL", (deal,))
                except Exception:
                    notes_ob = notes_df
                flat = None
                if "original_balance" in notes_ob.columns and notes_ob["original_balance"].notna().any():
                    ob = notes_ob["original_balance"].fillna(0)
                    if ob.sum() > 0:
                        flat = float((notes_ob["coupon_rate"] * ob).sum() / ob.sum())
                if flat is None:
                    flat = float(notes_df["coupon_rate"].mean())
                if flat and flat > 0:
                    if init_cod is None:
                        init_cod = flat
                    if curr_cod is None:
                        curr_cod = flat

        # Fallback: rough estimate from avg loan interest rate
        if init_cod is None or curr_cod is None:
            avg_rate_fb = q("SELECT AVG(original_interest_rate) as r FROM loans WHERE deal=? AND original_interest_rate IS NOT NULL", (deal,))
            if not avg_rate_fb.empty and avg_rate_fb.iloc[0]["r"]:
                rough = float(avg_rate_fb.iloc[0]["r"]) * 0.4
                if init_cod is None:
                    init_cod = rough
                if curr_cod is None:
                    curr_cod = rough

        # Latest pool balance — pull from the servicer cert's "Ending Pool Balance"
        # (authoritative) with a fall-back to the latest monthly_summary row.
        cert_totals = _cert_totals(deal)
        latest_bal = cert_totals.get("ending_pool_balance")
        if latest_bal is None:
            # date-sorted pick (reporting_period_end is "MM-DD-YYYY" which sorts
            # wrong as a string; sort in Python via the normalized date)
            ms_rows = q("SELECT reporting_period_end, total_balance FROM monthly_summary "
                        "WHERE deal=? AND total_balance IS NOT NULL", (deal,))
            if not ms_rows.empty:
                ms_rows["period"] = ms_rows["reporting_period_end"].apply(nd)
                ms_rows = ms_rows.sort_values("period")
                latest_bal = float(ms_rows.iloc[-1]["total_balance"])
        pool_factor = latest_bal / init_bal if (latest_bal and init_bal and init_bal > 0) else None

        equity = q("SELECT SUM(residual_cash) as total_residual FROM pool_performance WHERE deal=? AND residual_cash IS NOT NULL", (deal,))
        total_residual = equity.iloc[0]["total_residual"] if not equity.empty and equity.iloc[0]["total_residual"] else 0
        equity_pct = total_residual / init_bal if (init_bal and init_bal > 0) else None

        # Cumulative loss rate — authoritative from latest cert
        cum_loss_rate = get_cum_net_loss_rate(deal, init_bal)

        rows.append({
            "Deal": deal,
            "Avg FICO": f"{avg_fico:.0f}" if avg_fico else "-",
            "Initial Avg Consumer Rate": f"{init_wac:.2%}" if init_wac is not None else None,
            "Current Avg Consumer Rate": f"{curr_wac:.2%}" if curr_wac is not None else None,
            "Initial Avg Trust Cost of Debt": f"{init_cod:.2%}" if init_cod is not None else None,
            "Current Avg Trust Cost of Debt": f"{curr_cod:.2%}" if curr_cod is not None else None,
            "Init Balance": fm(init_bal),
            "Pool Factor": f"{pool_factor:.1%}" if pool_factor is not None else "-",
            "Cum Loss": f"{cum_loss_rate:.2%}" if cum_loss_rate is not None else "-",
            "Equity Dist": f"{equity_pct:.2%}" if equity_pct is not None else "-",
        })

    if rows:
        summary_df = pd.DataFrame(rows)
        # Drop columns where ALL values are None (no deal has data for that metric)
        for col in ["Initial Avg Consumer Rate", "Current Avg Consumer Rate",
                     "Initial Avg Trust Cost of Debt", "Current Avg Trust Cost of Debt"]:
            if col in summary_df.columns and summary_df[col].isna().all():
                summary_df = summary_df.drop(columns=[col])
                logger.warning(f"[{title}] Dropped column '{col}' — no data for any deal")
            elif col in summary_df.columns:
                summary_df[col] = summary_df[col].fillna("-")
        h += f"<h3>{title} — Summary</h3>" + table_html(summary_df, cls="compare")

    # ── Cumulative Loss Curve (by deal age in months) ──
    # Uses cert-authoritative cum-net-loss values (parsed from every cached
    # servicer cert) rather than cumsum'ing monthly_summary period flows,
    # which undercount any deal with gaps in ABS-EE ingestion.
    traces = []
    for i, deal in enumerate(deals):
        orig_bal = get_orig_bal(deal)
        if not orig_bal or orig_bal <= 0:
            continue
        series = _cum_net_loss_series(deal)
        if not series:
            continue
        months = list(range(1, len(series) + 1))
        rates = [round(cn / orig_bal, 6) for _, cn in series]
        traces.append({
            "x": months,
            "y": rates,
            "type": "scatter",
            "mode": "lines",
            "name": deal,
            "line": {"color": COLORS[i % len(COLORS)]},
        })

    if traces:
        h += chart(traces, {
            "title": f"{title} — Cumulative Net Loss Rate by Deal Age",
            "xaxis": {"title": "Deal Age (Months)"},
            "yaxis": {"tickformat": ".2%", "title": "Cum Net Loss (% of Orig Bal)"},
            "hovermode": "x unified",
            "legend": {"orientation": "h", "y": -0.3},
        }, height=450)

    # ── Pool Factor vs Month, Cum Loss vs Pool Factor, Excess Spread,
    #    30+ DQ Rate, Annualized Net Charge-Off Rate ──
    pf_traces = []       # x=calendar period, y=pool_factor
    pf_loss_traces = []  # x=pool_factor, y=cum net loss rate (chronological line)
    spread_traces = []   # x=calendar period, y=WAC - CoD
    dq_traces = []       # x=deal age, y=30+ DQ balance / total balance
    co_traces = []       # x=deal age, y=annualized net charge-off rate
    note_bal_cols = {"A1": "note_balance_a1", "A2": "note_balance_a2", "A3": "note_balance_a3",
                     "A4": "note_balance_a4", "B": "note_balance_b", "C": "note_balance_c",
                     "D": "note_balance_d", "N": "note_balance_n"}

    for i, deal in enumerate(deals):
        color = COLORS[i % len(COLORS)]
        orig_bal = get_orig_bal(deal)
        if not orig_bal or orig_bal <= 0:
            continue

        # Pool factor + cum loss + roll rates from monthly_summary
        ms = q("SELECT reporting_period_end, total_balance, period_chargeoffs, period_recoveries, "
               "dq_30_balance, dq_60_balance, dq_90_balance, dq_120_plus_balance "
               "FROM monthly_summary WHERE deal=? ORDER BY reporting_period_end", (deal,))
        if not ms.empty:
            ms["period"] = ms["reporting_period_end"].apply(nd)
            ms = ms.sort_values("period").reset_index(drop=True)
            ms["pool_factor"] = ms["total_balance"].astype(float) / orig_bal
            pf_traces.append({
                "x": list(range(1, len(ms) + 1)),
                "y": [round(v, 6) for v in ms["pool_factor"].tolist()],
                "type": "scatter", "mode": "lines", "name": deal,
                "line": {"color": color},
            })

            # Loss vs Pool Factor: pair cert-authoritative cum loss with the
            # pool-performance ending balance for the same distribution date.
            # (monthly_summary cumsum undercounts for deals with ABS-EE gaps.)
            loss_series = _cum_net_loss_series(deal)
            if loss_series:
                pool_bal = q("SELECT distribution_date, ending_pool_balance FROM pool_performance "
                             "WHERE deal=?", (deal,))
                bal_by_dt = {}
                for _, r in pool_bal.iterrows():
                    if r["ending_pool_balance"]:
                        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                            try:
                                bal_by_dt[datetime.strptime(str(r["distribution_date"]).strip()[:10], fmt)] = float(r["ending_pool_balance"])
                                break
                            except (ValueError, TypeError):
                                pass
                pf_x, pf_y = [], []
                for dt, cn in loss_series:
                    bal = bal_by_dt.get(dt)
                    if bal is None:
                        continue
                    pf_x.append(round(bal / orig_bal, 6))
                    pf_y.append(round(cn / orig_bal, 6))
                if pf_x:
                    pf_loss_traces.append({
                        "x": pf_x, "y": pf_y,
                        "type": "scatter", "mode": "lines+markers", "name": deal,
                        "line": {"color": color},
                        "marker": {"size": 4},
                    })

            # 30+ DQ rate: per-period 31-60 + 61-90 + 91-120 / ending pool balance,
            # parsed from each cached servicer cert. Matches the cert's bucket
            # definition (no 120+ bucket — those loans are charged off).
            dq_series = _cert_dq_series(deal)
            if dq_series:
                dq_traces.append({
                    "x": list(range(1, len(dq_series) + 1)),
                    "y": [round(dq / epb, 6) if epb else 0 for _, dq, epb in dq_series],
                    "type": "scatter", "mode": "lines", "name": deal,
                    "line": {"color": color},
                })

            # Prior-month balance series for the annualized charge-off chart.
            bal = ms["total_balance"].astype(float)

            # Annualized net charge-off rate: (CO - recoveries) * 12 / avg pool balance.
            # Uses prior-month balance as the denominator (standard industry form).
            # Skip month 1 where there's no prior-month balance.
            prev_bal = bal.shift(1)
            net_co = (ms["period_chargeoffs"].fillna(0) - ms["period_recoveries"].fillna(0)).astype(float)
            co_rate = (net_co * 12.0) / prev_bal.where(prev_bal > 0)
            co_x = []; co_y = []
            for idx, v in enumerate(co_rate.tolist()):
                if idx == 0 or v is None or pd.isna(v):
                    continue
                co_x.append(idx + 1)   # deal age = 1-based index
                co_y.append(round(float(v), 6))
            if co_x:
                co_traces.append({
                    "x": co_x, "y": co_y,
                    "type": "scatter", "mode": "lines", "name": deal,
                    "line": {"color": color},
                })

        # Excess spread: WAC − CoD aligned on collection-period (year, month).
        # WAC source (pool_performance.weighted_avg_apr for Prime; monthly_summary
        # .weighted_avg_coupon for Non-Prime, which doesn't populate WAC in the
        # servicer report) is keyed by the month-end of the collection period.
        # CoD comes from pool_performance — but those rows use the distribution
        # date, which is ~10 days after the collection period it reports on.
        # Shifting the distribution month back by one gives the collection month.
        pool = q("SELECT * FROM pool_performance WHERE deal=? ORDER BY dist_date_iso", (deal,))
        if pool.empty:
            continue
        pool["period"] = pool["distribution_date"].apply(nd)
        pool = pool.sort_values("period").reset_index(drop=True)

        def _ym(s):
            s = str(s).strip()
            if len(s) >= 7 and s[4] in "-/":
                try:
                    return (int(s[:4]), int(s[5:7]))
                except ValueError:
                    return None
            return None

        # WAC by collection month
        wac_by_col = {}
        if "weighted_avg_apr" in pool.columns and pool["weighted_avg_apr"].notna().any():
            for _, row in pool.iterrows():
                ym = _ym(row["period"])
                w = row["weighted_avg_apr"]
                if ym and pd.notna(w):
                    col_ym = (ym[0], ym[1] - 1) if ym[1] > 1 else (ym[0] - 1, 12)
                    wac_by_col[col_ym] = float(w)
        else:
            wac_ms = q("SELECT reporting_period_end, weighted_avg_coupon FROM monthly_summary "
                       "WHERE deal=? AND weighted_avg_coupon IS NOT NULL ORDER BY reporting_period_end", (deal,))
            for _, row in wac_ms.iterrows():
                ym = _ym(nd(row["reporting_period_end"]))
                if ym:
                    wac_by_col[ym] = float(row["weighted_avg_coupon"])

        # CoD by collection month
        try:
            notes_df = q("SELECT class, coupon_rate FROM notes WHERE deal=? AND coupon_rate IS NOT NULL", (deal,))
        except Exception:
            notes_df = pd.DataFrame()
        norm_rate_lookup = {}
        if not notes_df.empty:
            for cls, rate in zip(notes_df["class"], notes_df["coupon_rate"]):
                norm = cls.upper().replace("-", "").replace(" ", "").replace("CLASS", "")
                norm_rate_lookup[norm] = rate
        for col in note_bal_cols.values():
            if col in pool.columns:
                pool[col] = pool[col].ffill()

        cod_by_col = {}
        has_ni = "total_note_interest" in pool.columns
        has_nb = "aggregate_note_balance" in pool.columns
        for _, row in pool.iterrows():
            ym = _ym(row["period"])
            if not ym:
                continue
            col_ym = (ym[0], ym[1] - 1) if ym[1] > 1 else (ym[0] - 1, 12)
            cod_val = None
            if has_ni and has_nb:
                ni = row.get("total_note_interest")
                nb = row.get("aggregate_note_balance")
                if pd.notna(ni) and pd.notna(nb) and float(nb) > 0 and float(ni) > 0:
                    v = float(ni) / float(nb) * 12
                    if 0 < v < 0.25:
                        cod_val = v
            if cod_val is None and norm_rate_lookup:
                w_sum, t_bal = 0.0, 0.0
                for cls, col in note_bal_cols.items():
                    if col in pool.columns and cls in norm_rate_lookup:
                        bal = row.get(col)
                        if pd.notna(bal) and float(bal) > 0:
                            w_sum += norm_rate_lookup[cls] * float(bal)
                            t_bal += float(bal)
                if t_bal > 0:
                    cod_val = w_sum / t_bal
            if cod_val is not None:
                cod_by_col[col_ym] = cod_val

        keys = sorted(set(wac_by_col) & set(cod_by_col))
        # Drop the first period. The first servicer cert reports note interest
        # for a partial accrual period (closing date → first payment date,
        # typically 20-30 days), but our CoD annualizes by ×12. That understates
        # CoD on the first observation and creates a ~1-2% upward spike in
        # excess spread at month 1 on every deal — a chart artifact, not a
        # real jump in profitability.
        if len(keys) > 1:
            keys = keys[1:]
        if keys:
            spread_traces.append({
                "x": list(range(1, len(keys) + 1)),
                "y": [round(wac_by_col[k] - cod_by_col[k], 6) for k in keys],
                "type": "scatter", "mode": "lines", "name": deal,
                "line": {"color": color},
            })

    if pf_traces:
        h += chart(pf_traces, {
            "title": f"{title} — Pool Factor by Deal Age",
            "xaxis": {"title": "Deal Age (Months)"},
            "yaxis": {"tickformat": ".0%", "title": "Pool Factor (Remaining / Original)"},
            "hovermode": "x unified",
            "legend": {"orientation": "h", "y": -0.3},
        }, height=450)

    if pf_loss_traces:
        h += chart(pf_loss_traces, {
            "title": f"{title} — Cumulative Net Loss vs Pool Factor",
            "xaxis": {"title": "Pool Factor (Remaining / Original)",
                      "tickformat": ".0%", "autorange": "reversed"},
            "yaxis": {"tickformat": ".2%", "title": "Cum Net Loss (% of Orig Bal)"},
            "hovermode": "closest",
            "legend": {"orientation": "h", "y": -0.3},
        }, height=450)

    if dq_traces:
        h += chart(dq_traces, {
            "title": f"{title} — 30+ Day Delinquency Rate by Deal Age",
            "xaxis": {"title": "Deal Age (Months)"},
            "yaxis": {"tickformat": ".2%", "title": "30+ DQ Balance / Pool Balance"},
            "hovermode": "x unified",
            "legend": {"orientation": "h", "y": -0.3},
        }, height=450)

    if co_traces:
        h += chart(co_traces, {
            "title": f"{title} — Annualized Net Charge-Off Rate by Deal Age",
            "xaxis": {"title": "Deal Age (Months)"},
            "yaxis": {"tickformat": ".2%", "title": "Net Charge-Offs × 12 / Prior Month Balance"},
            "hovermode": "x unified",
            "legend": {"orientation": "h", "y": -0.3},
        }, height=450)

    if spread_traces:
        h += chart(spread_traces, {
            "title": f"{title} — Excess Spread by Deal Age (Consumer Rate − Trust Cost of Debt)",
            "xaxis": {"title": "Deal Age (Months)"},
            "yaxis": {"tickformat": ".2%", "title": "Excess Spread"},
            "hovermode": "x unified",
            "legend": {"orientation": "h", "y": -0.3},
        }, height=450)

    return h


def _loss_forecast_buildup_tables(model_results):
    """Per-deal lifetime loss-forecast build-up using the conditional Markov
    forward simulation (see carvana_abs/conditional_markov.py).

    For each currently-active loan we walk its (state, age, balance) forward
    month-by-month to original term, applying transition probabilities binned
    by (tier, current_state, age_bucket, FICO_bucket, LTV_bucket, modified)
    and amortizing the balance via empirical paydown curves binned by
    (tier, term_bucket, age). Mass entering Default at month t contributes
    expected loss = mass × balance(t) × LGD(tier, age, FICO, LTV).

    Output columns:
        Realized $/% — cert's cumulative net charge-off
        DQ pipeline $ — sum of expected future loss for loans currently 1+ payment behind
        Performing future $ — same for loans currently up-to-date
        Total $ midpoint — realized + dq + performing
        Total $ −1σ / +1σ — total ± 1 standard deviation of forecast (Bernoulli per loan, summed)
    """
    # Read from dashboard.db model_results['conditional_markov'] directly so
    # the build-up table picks up forecasts written by conditional_markov.py
    # without the model_results JSON blob having to be re-saved.
    cm = q("SELECT value FROM model_results WHERE key='conditional_markov'")
    if cm.empty:
        return ""
    cm_data = json.loads(cm.iloc[0]["value"])
    by_deal = cm_data.get("by_deal", {})
    p_def_ref = cm_data.get("p_default_reference", {})

    def build_for(deals, title):
        rows = []
        for deal in deals:
            d = by_deal.get(deal)
            if not d: continue
            orig = get_orig_bal(deal)
            if not orig or orig <= 0: continue
            realized = d["realized"]; dq = d["dq_pending"]; perf = d["performing_future"]
            mid = d["total_expected"]
            lo = d["total_minus_1sd"]; hi = d["total_plus_1sd"]
            cal_factor = d.get("calibration_factor", 1.0)
            def pct(x): return f"{x/orig:.2%}" if orig else "-"
            rows.append({
                "Deal": deal,
                "Active Loans": f"{d['active_loans']:,}",
                "Realized $": fm(realized),
                "Realized %": pct(realized),
                "DQ Pipeline $": fm(dq),
                "Performing Future $": fm(perf),
                "Cohort Cal": f"{cal_factor:.2f}×",
                "Total $ −1σ": fm(lo),
                "Total $ midpoint": fm(mid),
                "Total $ +1σ": fm(hi),
                "Total %": pct(mid),
            })
        if not rows:
            return ""
        return (f"<h3>{title} — Lifetime Loss Forecast Build-Up</h3>"
                + table_html(pd.DataFrame(rows), cls="compare"))

    h = ""
    h += build_for(PRIME_DEALS, "Prime")
    h += build_for(NONPRIME_DEALS, "Non-Prime")

    # Reference table: 1-month default + payoff probabilities at the most
    # populated (state, age, FICO) cells. Lets you eyeball the model.
    for tier in ("Prime", "NonPrime"):
        rows = p_def_ref.get(tier, [])
        if not rows: continue
        # Collapse to most-populated cells, sort by N descending, top 30
        rows_sorted = sorted(rows, key=lambda r: -r["n"])[:30]
        ref_df = pd.DataFrame([{
            "State": r["state"], "Age": r["age"], "FICO": r["fico"],
            "n obs": f"{r['n']:,}",
            "P(Default) 1mo": f"{r['p_default_1mo']:.4%}",
            "P(Payoff) 1mo": f"{r['p_payoff_1mo']:.4%}",
        } for r in rows_sorted])
        h += f"<h3>{tier} — One-month transition probabilities (top 30 cells)</h3>"
        h += table_html(ref_df, cls="compare")

    if h:
        h = ("<div class=\"tc\">" + h
             + "<p style=\"font-size:.75rem;color:#666;margin-top:8px;\">"
             "<b>Realized</b> from the servicer cert's cumulative net charge-off line. "
             "<b>DQ pipeline</b> + <b>Performing future</b> are the per-loan forward "
             "simulation results for active loans currently delinquent / current. "
             "Transitions binned by tier × state × age × FICO × LTV × modified flag "
             "with sparse-cell fallbacks. Balance amortized monthly via empirical "
             "paydown curves observed in performing loans (modified loans use a "
             "separate curve or held flat if too sparse). LGD per defaulted loan "
             "binned by tier × age × FICO × LTV. ±1σ accumulates per-loan "
             "Bernoulli variance — captures within-portfolio dispersion, not macro "
             "shock.</p></div>")
    return h


def generate_model_content():
    """Generate HTML for the Default Model analysis section."""
    mr = None
    try:
        mr = q("SELECT value FROM model_results WHERE key='default_model'")
    except Exception:
        pass

    # If no pre-computed results, try to run the model inline
    if mr is None or mr.empty:
        logger.info("No pre-computed model results found, running model inline...")
        try:
            import importlib.util
            model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default_model.py")
            spec = importlib.util.spec_from_file_location("default_model", model_path)
            dm = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(dm)
            dm.DASHBOARD_DB = ACTIVE_DB
            dm.OUTPUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "deploy", "LAST_MODEL_RESULTS.json")
            df = dm.load_data(ACTIVE_DB)
            logger.info(f"Inline model: loaded {len(df)} loans")
            if len(df) > 0:
                df, feature_cols = dm.engineer_features(df)
                results = dm.train_models(df, feature_cols)
                if results:
                    dm.save_results(results, ACTIVE_DB, dm.OUTPUT_JSON)
                    mr = q("SELECT value FROM model_results WHERE key='default_model'")
        except Exception as e:
            logger.error(f"Inline model failed: {e}")

    if mr is None or mr.empty:
        return "<p>Default model could not be computed.</p>"

    results = json.loads(mr.iloc[0]["value"])
    ds = results["dataset"]
    h = ""

    # ── Dataset Summary ──
    h += f"""<div class="metrics">
<div class="metric"><div class="mv">{ds['total_loans']:,}</div><div class="ml">Total Loans</div></div>
<div class="metric"><div class="mv">{ds['defaults']:,}</div><div class="ml">Defaults</div></div>
<div class="metric"><div class="mv">{ds['default_rate']:.2%}</div><div class="ml">Default Rate</div></div>
<div class="metric"><div class="mv">{ds['train_size']:,}</div><div class="ml">Train Set</div></div>
<div class="metric"><div class="mv">{ds['test_size']:,}</div><div class="ml">Test Set</div></div>
</div>"""

    # ── Loss Forecast Build-Up (per deal, split Prime vs Non-Prime) ──
    h += _loss_forecast_buildup_tables(results)

    # ── Model Comparison Table ──
    rows = []
    for name, m in results["models"].items():
        rows.append({
            "Model": name.replace("_", " ").title(),
            "Accuracy": f"{m['accuracy']:.1%}",
            "AUC-ROC": f"{m['auc_roc']:.3f}",
            "Precision": f"{m['precision']:.1%}",
            "Recall": f"{m['recall']:.1%}",
            "F1 Score": f"{m['f1']:.1%}",
        })
    h += "<h3>Model Performance</h3>" + table_html(pd.DataFrame(rows), cls="compare")

    # ── ROC Curves ──
    roc_traces = []
    colors = {"logistic_regression": "#1976D2", "random_forest": "#D32F2F"}
    for name, m in results["models"].items():
        roc = m["roc_curve"]
        roc_traces.append({
            "x": roc["fpr"], "y": roc["tpr"],
            "type": "scatter", "mode": "lines",
            "name": f"{name.replace('_',' ').title()} (AUC={m['auc_roc']:.3f})",
            "line": {"color": colors.get(name, "#388E3C")},
        })
    roc_traces.append({
        "x": [0, 1], "y": [0, 1], "type": "scatter", "mode": "lines",
        "name": "Random (AUC=0.5)", "line": {"color": "#999", "dash": "dash"},
    })
    h += chart(roc_traces, {
        "title": "ROC Curve",
        "xaxis": {"title": "False Positive Rate"},
        "yaxis": {"title": "True Positive Rate"},
        "legend": {"orientation": "h", "y": -0.2},
    })

    # ── Feature Importance (Random Forest) ──
    rf = results["models"].get("random_forest", {})
    if "feature_importance" in rf:
        fi = rf["feature_importance"]
        sorted_fi = sorted(fi.items(), key=lambda x: x[1], reverse=True)
        h += chart([{
            "x": [kv[0] for kv in sorted_fi],
            "y": [kv[1] for kv in sorted_fi],
            "type": "bar", "marker": {"color": "#1976D2"},
        }], {"title": "Feature Importance (Random Forest)", "yaxis": {"tickformat": ".1%"}})

    # ── Logistic Regression Coefficients ──
    lr = results["models"].get("logistic_regression", {})
    if "coefficients" in lr:
        coefs = lr["coefficients"]
        sorted_c = sorted(coefs.items(), key=lambda x: abs(x[1]), reverse=True)
        colors_c = ["#D32F2F" if v < 0 else "#388E3C" for _, v in sorted_c]
        h += chart([{
            "x": [kv[0] for kv in sorted_c],
            "y": [kv[1] for kv in sorted_c],
            "type": "bar", "marker": {"color": colors_c},
        }], {"title": "Logistic Regression Coefficients (standardized)",
             "yaxis": {"title": "Coefficient"}})

    # ── Confusion Matrices ──
    for name, m in results["models"].items():
        cm = m["confusion_matrix"]
        cm_df = pd.DataFrame({
            "": ["Actual No Default", "Actual Default"],
            "Predicted No Default": [f"{cm[0][0]:,}", f"{cm[1][0]:,}"],
            "Predicted Default": [f"{cm[0][1]:,}", f"{cm[1][1]:,}"],
        })
        h += f"<h3>Confusion Matrix — {name.replace('_',' ').title()}</h3>" + table_html(cm_df, cls="compare")

    # ── Segment Analysis: Predicted vs Actual ──
    segs = results.get("segments", {})

    for seg_key, seg_title in [("by_fico", "Default Rate by FICO Score"),
                                ("by_vintage", "Default Rate by Origination Year"),
                                ("by_ltv", "Default Rate by LTV"),
                                ("by_rate", "Default Rate by Interest Rate")]:
        seg = segs.get(seg_key)
        if not seg:
            continue
        h += chart([
            {"x": seg["labels"], "y": seg["actual_rate"], "type": "bar",
             "name": "Actual", "marker": {"color": "#D32F2F"}},
            {"x": seg["labels"], "y": seg["predicted_rate"], "type": "bar",
             "name": "Predicted", "marker": {"color": "#1976D2"}},
        ], {"title": seg_title, "barmode": "group",
            "yaxis": {"tickformat": ".1%"}, "hovermode": "x unified",
            "legend": {"orientation": "h", "y": -0.2}})
        # Table
        tbl_rows = []
        for i, label in enumerate(seg["labels"]):
            row = {"Segment": label, "Loans": f"{seg['loans'][i]:,}",
                   "Actual Default": f"{seg['actual_rate'][i]:.2%}",
                   "Predicted Default": f"{seg['predicted_rate'][i]:.2%}"}
            tbl_rows.append(row)
        h += table_html(pd.DataFrame(tbl_rows), cls="compare")

    # ── Loss Severity ──
    sev = segs.get("loss_severity")
    if sev:
        h += f"""<h3>Loss Severity (Defaulted Loans Only)</h3>
<div class="metrics">
<div class="metric"><div class="mv">{sev['total_defaulted']:,}</div><div class="ml">Defaulted Loans</div></div>
<div class="metric"><div class="mv">{fm(sev['avg_chargeoff'])}</div><div class="ml">Avg Chargeoff</div></div>
<div class="metric"><div class="mv">{fm(sev['avg_recovery'])}</div><div class="ml">Avg Recovery</div></div>
<div class="metric"><div class="mv">{fm(sev['avg_net_loss'])}</div><div class="ml">Avg Net Loss</div></div>
<div class="metric"><div class="mv">{sev['recovery_rate']:.1%}</div><div class="ml">Recovery Rate</div></div>
<div class="metric"><div class="mv">{fm(sev['median_chargeoff'])}</div><div class="ml">Median Chargeoff</div></div>
</div>"""

    return h


# ---------------------------------------------------------------------------
# Residual Economics Tab  (landing page — first/default tab)
# ---------------------------------------------------------------------------

def _safe_div(a, b):
    """Return a/b or None when b is zero/None."""
    if b is None or b == 0:
        return None
    return a / b


def generate_economics_tab():
    """Build the residual-economics landing-page HTML.

    Returns a single HTML string containing:
      1. A summary economics table (one row per deal)
      2. A methodology writeup with inline diagrams
    """
    import math

    # ── 1. Gather deal_terms from the *full* (raw) DBs ──────────────────
    carvana_full = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db", "carvana_abs.db")
    carmax_full = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "carmax_abs", "db", "carmax_abs.db")

    deals_data = []  # list of dicts, one per deal

    for db_path, issuer in [(carvana_full, "CRVNA"), (carmax_full, "CARMX")]:
        if not os.path.exists(db_path):
            continue
        conn = sqlite3.connect(db_path)
        # Check if deal_terms exists
        has_dt = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='deal_terms'"
        ).fetchone()[0]
        if not has_dt:
            conn.close()
            continue

        rows = conn.execute("""
            SELECT deal, initial_pool_balance, weighted_avg_coupon,
                   servicing_fee_annual_pct, cutoff_date,
                   class_a1_pct, class_a2_pct, class_a3_pct, class_a4_pct,
                   class_b_pct, class_c_pct, class_d_pct, class_n_pct,
                   initial_oc_pct, cnl_trigger_schedule, dq_trigger_pct,
                   dq_trigger_schedule, oc_target_pct, oc_floor_pct,
                   initial_reserve_pct, reserve_floor_pct
            FROM deal_terms
            WHERE terms_extracted = 1
            ORDER BY cutoff_date
        """).fetchall()
        cols = ["deal", "initial_pool_balance", "weighted_avg_coupon",
                "servicing_fee_annual_pct", "cutoff_date",
                "class_a1_pct", "class_a2_pct", "class_a3_pct", "class_a4_pct",
                "class_b_pct", "class_c_pct", "class_d_pct", "class_n_pct",
                "initial_oc_pct", "cnl_trigger_schedule", "dq_trigger_pct",
                "dq_trigger_schedule", "oc_target_pct", "oc_floor_pct",
                "initial_reserve_pct", "reserve_floor_pct"]
        for row in rows:
            d = dict(zip(cols, row))
            d["issuer"] = issuer
            # Sanity: skip deals with clearly bad pool balance (>$5B for a single deal)
            if d["initial_pool_balance"] and d["initial_pool_balance"] > 5e9:
                continue
            # Skip deals with no pool balance
            if not d["initial_pool_balance"]:
                continue
            deals_data.append(d)
        conn.close()

    if not deals_data:
        return "<p style='padding:16px'>No deal terms data available.</p>"

    # ── 2. Consumer WAC from loans tables ────────────────────────────────
    consumer_wac = {}
    for db_path, db_label in [
        (os.path.join(os.path.dirname(os.path.abspath(__file__)), "db", "dashboard.db"), "crvna_dash"),
        (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "carmax_abs", "db", "dashboard.db"), "carmx_dash"),
    ]:
        if not os.path.exists(db_path):
            continue
        conn = sqlite3.connect(db_path)
        has_loans = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='loans'"
        ).fetchone()[0]
        if has_loans:
            wac_rows = conn.execute("""
                SELECT deal,
                       SUM(original_interest_rate * original_loan_amount) / SUM(original_loan_amount)
                FROM loans
                GROUP BY deal
            """).fetchall()
            for r in wac_rows:
                consumer_wac[r[0]] = r[1]
        conn.close()

    # ── 3. Pool performance aggregates ───────────────────────────────────
    perf_agg = {}  # deal -> {total_interest, total_servicing_fee, cum_losses, periods, max_bal}
    for db_path in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "db", "dashboard.db"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "carmax_abs", "db", "dashboard.db"),
    ]:
        if not os.path.exists(db_path):
            continue
        conn = sqlite3.connect(db_path)
        has_pp = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='pool_performance'"
        ).fetchone()[0]
        if not has_pp:
            conn.close()
            continue
        pp_rows = conn.execute("""
            SELECT deal,
                   SUM(interest_collections) as total_interest,
                   SUM(actual_servicing_fee) as total_svc,
                   MAX(cumulative_net_losses) as cum_losses,
                   COUNT(*) as periods,
                   MAX(beginning_pool_balance) as max_bal
            FROM pool_performance
            WHERE dist_date_iso IS NOT NULL
            GROUP BY deal
        """).fetchall()
        for r in pp_rows:
            perf_agg[r[0]] = {
                "total_interest": r[1] or 0,
                "total_servicing_raw": r[2] or 0,
                "cum_losses": r[3] or 0,
                "periods": r[4] or 0,
                "max_bal": r[5] or 0,
            }
        conn.close()

    # ── 4. Model forecasts (from model_results in Carvana dashboard DB) ─
    model_forecasts = {}  # deal -> {predicted_default_rate, actual_default_rate}
    crvna_dash = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db", "dashboard.db")
    if os.path.exists(crvna_dash):
        conn = sqlite3.connect(crvna_dash)
        has_mr = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='model_results'"
        ).fetchone()[0]
        if has_mr:
            try:
                import json as _json
                raw = conn.execute("SELECT value FROM model_results WHERE key='default_model'").fetchone()
                if raw:
                    mdata = _json.loads(raw[0])
                    lf = mdata.get("segments", {}).get("lifetime_forecast_by_deal", {})
                    for deal, info in lf.items():
                        orig = info.get("total_orig_amount", 0)
                        if orig > 0:
                            model_forecasts[deal] = {
                                "predicted_loss_pct": info["predicted_default_amount"] / orig,
                                "actual_loss_pct": info["actual_default_amount"] / orig,
                            }
            except Exception:
                pass
        conn.close()

    # ── 5. Check for Markov deal_forecasts table ─────────────────────────
    markov_forecasts = {}  # deal -> {at_issuance_cnl_pct, current_projected_cnl_pct, wal, breach_prob}
    for db_path in [carvana_full, carmax_full]:
        if not os.path.exists(db_path):
            continue
        conn = sqlite3.connect(db_path)
        has_df = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='deal_forecasts'"
        ).fetchone()[0]
        if has_df:
            try:
                df_rows = conn.execute("SELECT * FROM deal_forecasts").fetchall()
                df_cols = [d[1] for d in conn.execute("PRAGMA table_info(deal_forecasts)").fetchall()]
                for row in df_rows:
                    rd = dict(zip(df_cols, row))
                    markov_forecasts[rd.get("deal", "")] = rd
            except Exception:
                pass
        conn.close()

    has_markov = bool(markov_forecasts)

    # ── 6. Compute economics for each deal ───────────────────────────────
    for d in deals_data:
        deal = d["deal"]
        ipb = d["initial_pool_balance"]

        # Capital structure
        aaa_pct = sum(filter(None, [d.get("class_a1_pct"), d.get("class_a2_pct"),
                                     d.get("class_a3_pct"), d.get("class_a4_pct")])) or 0
        aa_pct = d.get("class_b_pct") or 0
        a_pct = d.get("class_c_pct") or 0
        bbb_pct = d.get("class_d_pct") or 0
        oc_pct = d.get("initial_oc_pct") or 0
        # If OC > 50%, it's likely a parse error (e.g. 99.6% for non-prime = residual, not OC)
        # Compute OC as 1 - sum of all notes
        notes_total = aaa_pct + aa_pct + a_pct + bbb_pct + (d.get("class_n_pct") or 0)
        if notes_total > 0.01 and notes_total < 1.0:
            computed_oc = 1.0 - notes_total
            if computed_oc > 0:
                oc_pct = computed_oc

        d["aaa_pct"] = aaa_pct
        d["aa_pct"] = aa_pct
        d["a_pct"] = a_pct
        d["bbb_pct"] = bbb_pct
        d["oc_pct"] = oc_pct

        # Consumer WAC
        d["consumer_wac"] = consumer_wac.get(deal)

        # Cost of debt
        d["cost_of_debt"] = d.get("weighted_avg_coupon")

        # Excess spread / yr
        if d["consumer_wac"] and d["cost_of_debt"]:
            d["excess_spread_yr"] = d["consumer_wac"] - d["cost_of_debt"]
        else:
            d["excess_spread_yr"] = None

        # WAL estimate from pool_performance (simple: sum of (balance_i / initial_balance) / 12)
        perf = perf_agg.get(deal, {})
        periods = perf.get("periods", 0)

        # Markov WAL if available
        mf = markov_forecasts.get(deal, {})
        if mf.get("wal"):
            d["wal"] = mf["wal"]
        elif periods > 0 and ipb > 0:
            # Estimate WAL: for seasoned deals, compute actual weighted average life from balances
            # Simple approximation: midpoint of amortization
            max_bal = perf.get("max_bal", ipb)
            # Use number of periods as proxy for maturity
            # Better: WAL ≈ periods_so_far * avg_factor / 12 for amortizing pool
            # We'll estimate total WAL assuming roughly linear amortization
            # For deals still outstanding: extrapolate
            # Simple: WAL ≈ WAT / 2 for a roughly even amortization
            # Average original term from loans if available
            d["wal"] = None  # Will estimate below
        else:
            d["wal"] = None

        # Servicing fee
        svc_annual = d.get("servicing_fee_annual_pct") or 0

        # Expected losses
        if mf.get("at_issuance_cnl_pct"):
            d["expected_loss_pct"] = mf["at_issuance_cnl_pct"]
        elif deal in model_forecasts:
            d["expected_loss_pct"] = model_forecasts[deal]["predicted_loss_pct"]
        else:
            d["expected_loss_pct"] = None

        # Realized/actual losses
        if perf and ipb > 0:
            d["actual_cum_losses_pct"] = perf.get("cum_losses", 0) / ipb
        else:
            d["actual_cum_losses_pct"] = None

        # Projected losses (current model projection)
        if mf.get("current_projected_cnl_pct"):
            d["projected_loss_pct"] = mf["current_projected_cnl_pct"]
        elif deal in model_forecasts:
            d["projected_loss_pct"] = model_forecasts[deal]["actual_loss_pct"]
        else:
            d["projected_loss_pct"] = d.get("actual_cum_losses_pct")

        # Actual cumulative interest as % of initial pool
        if perf and ipb > 0:
            d["actual_cum_interest_pct"] = perf.get("total_interest", 0) / ipb
        else:
            d["actual_cum_interest_pct"] = None

        # Actual servicing as % of initial pool
        # For Carvana, actual_servicing_fee in pool_perf is the annual % (stored raw)
        # For CarMax, it's actual dollars. Detect by magnitude.
        if perf and ipb > 0:
            raw_svc = perf.get("total_servicing_raw", 0)
            if raw_svc > 100:
                # Looks like dollar amounts (CarMax)
                d["actual_cum_servicing_pct"] = raw_svc / ipb
            else:
                # Carvana: use deal_terms servicing_fee_annual_pct * age_in_years
                age_years = periods / 12.0
                d["actual_cum_servicing_pct"] = svc_annual * age_years
        else:
            d["actual_cum_servicing_pct"] = None

        # % forecast complete (how much of pool has amortized)
        if perf and ipb > 0:
            latest_bal = perf.get("max_bal", ipb)
            # We need ending balance, not max. Let me use cum_losses + amortization proxy
            # Actually: pool factor = ending_balance / initial_balance
            # We stored max_bal. We need a different query for ending balance.
            # Approximate: fraction of interest collected vs expected
            d["pct_complete"] = None  # Will compute from WAL below
        else:
            d["pct_complete"] = None

        # Trigger risk
        if mf.get("breach_prob") is not None:
            d["trigger_risk"] = mf["breach_prob"]
        else:
            d["trigger_risk"] = None

    # ── 6b. WAL estimation from pool_performance balance series ──────────
    # Run a targeted query to get ending pool balances for WAL calc
    for db_path in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "db", "dashboard.db"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "carmax_abs", "db", "dashboard.db"),
    ]:
        if not os.path.exists(db_path):
            continue
        conn = sqlite3.connect(db_path)
        # Get ending balances by deal ordered by date
        wal_rows = conn.execute("""
            SELECT deal, ending_pool_balance
            FROM pool_performance
            WHERE dist_date_iso IS NOT NULL AND ending_pool_balance IS NOT NULL
            ORDER BY deal, dist_date_iso
        """).fetchall()
        conn.close()

        # Group by deal
        from collections import defaultdict
        deal_bals = defaultdict(list)
        for row in wal_rows:
            deal_bals[row[0]].append(row[1])

        for d in deals_data:
            if d.get("wal") is not None:
                continue
            deal = d["deal"]
            ipb = d["initial_pool_balance"]
            bals = deal_bals.get(deal, [])
            if not bals or not ipb:
                continue
            # WAL = sum of (balance_i / initial_balance) / 12 for monthly periods
            # This gives the actual weighted average life in years
            wal_sum = sum(b / ipb for b in bals) / 12.0
            periods = len(bals)
            # For in-progress deals, extrapolate assuming current paydown rate continues
            latest_bal = bals[-1] if bals else 0
            pool_factor = latest_bal / ipb if ipb > 0 else 0
            if pool_factor > 0.05:
                # Deal still outstanding — extrapolate
                # Monthly paydown rate
                if periods > 1:
                    # Average monthly principal paydown as fraction of initial
                    monthly_paydown = (1.0 - pool_factor) / periods
                    if monthly_paydown > 0:
                        remaining_months = pool_factor / monthly_paydown
                        # Add estimated remaining WAL contribution
                        # Remaining balance declines linearly from current to 0
                        remaining_wal = (pool_factor / 2.0) * (remaining_months / 12.0)
                        wal_sum += remaining_wal
            d["wal"] = round(wal_sum, 2)
            d["pool_factor"] = pool_factor
            d["pct_complete"] = 1.0 - pool_factor

    # ── 7. Compute derived economics columns ─────────────────────────────
    for d in deals_data:
        wal = d.get("wal")
        svc = d.get("servicing_fee_annual_pct") or 0

        # Total excess spread = excess/yr × WAL
        if d.get("excess_spread_yr") is not None and wal:
            d["total_excess_spread"] = d["excess_spread_yr"] * wal
        else:
            d["total_excess_spread"] = None

        # Servicing & other = servicing_fee × WAL
        if wal:
            d["total_servicing_cost"] = svc * wal
        else:
            d["total_servicing_cost"] = None

        # Expected residual = total excess - servicing - expected losses
        if (d.get("total_excess_spread") is not None and
                d.get("total_servicing_cost") is not None and
                d.get("expected_loss_pct") is not None):
            d["expected_residual"] = (d["total_excess_spread"]
                                      - d["total_servicing_cost"]
                                      - d["expected_loss_pct"])
        else:
            d["expected_residual"] = None

        # Actual/projected residual = actual interest - actual servicing - projected losses
        if (d.get("actual_cum_interest_pct") is not None and
                d.get("actual_cum_servicing_pct") is not None and
                d.get("projected_loss_pct") is not None):
            d["actual_residual"] = (d["actual_cum_interest_pct"]
                                    - d["actual_cum_servicing_pct"]
                                    - d["projected_loss_pct"])
        else:
            d["actual_residual"] = None

        # Variance
        if d.get("actual_residual") is not None and d.get("expected_residual") is not None:
            d["variance"] = d["actual_residual"] - d["expected_residual"]
        else:
            d["variance"] = None

    # ── 8. Build HTML table ──────────────────────────────────────────────
    def pf(v, decimals=2):
        """Format as percentage string."""
        if v is None:
            return '<span style="color:#999">—</span>'
        return f"{v*100:.{decimals}f}%"

    def pf_color(v, decimals=2):
        """Format percentage with green/red coloring."""
        if v is None:
            return '<span style="color:#999">—</span>'
        color = "#388E3C" if v >= 0 else "#D32F2F"
        return f'<span style="color:{color};font-weight:600">{v*100:.{decimals}f}%</span>'

    def dollar_hover(pct_val, ipb, decimals=2):
        """Return pct string with $ amount on hover."""
        if pct_val is None or ipb is None:
            return '<span style="color:#999">—</span>'
        dollar = pct_val * ipb
        dollar_str = fm(dollar)
        return f'<span title="{dollar_str}">{pct_val*100:.{decimals}f}%</span>'

    def trigger_badge(prob):
        """Color-coded trigger risk badge."""
        if prob is None:
            return '<span style="color:#999">—</span>'
        if prob < 0.10:
            return f'<span style="background:#C8E6C9;color:#2E7D32;padding:1px 6px;border-radius:4px;font-weight:600">{prob*100:.0f}%</span>'
        elif prob < 0.30:
            return f'<span style="background:#FFF9C4;color:#F57F17;padding:1px 6px;border-radius:4px;font-weight:600">{prob*100:.0f}%</span>'
        else:
            return f'<span style="background:#FFCDD2;color:#C62828;padding:1px 6px;border-radius:4px;font-weight:600">{prob*100:.0f}%</span>'

    # Separate Carvana Prime, CarMax, Carvana Non-Prime
    crvna_prime = [d for d in deals_data if d["issuer"] == "CRVNA" and "-P" in d["deal"]]
    crvna_nonprime = [d for d in deals_data if d["issuer"] == "CRVNA" and "-N" in d["deal"]]
    carmx_deals = [d for d in deals_data if d["issuer"] == "CARMX"]

    # Sort chronologically
    crvna_prime.sort(key=lambda x: x.get("cutoff_date") or "")
    crvna_nonprime.sort(key=lambda x: x.get("cutoff_date") or "")
    carmx_deals.sort(key=lambda x: x.get("cutoff_date") or "")

    # Interleave Carvana Prime and CarMax by cutoff date for main table
    prime_and_carmax = sorted(crvna_prime + carmx_deals, key=lambda x: x.get("cutoff_date") or "")

    def _build_table_rows(deal_list):
        rows_html = ""
        for d in deal_list:
            ipb = d["initial_pool_balance"]
            cutoff = d.get("cutoff_date") or "—"
            if cutoff != "—":
                # Format as Mon-YY
                try:
                    from datetime import datetime as _dt
                    dt = _dt.strptime(cutoff, "%Y-%m-%d")
                    cutoff = dt.strftime("%b-%y")
                except Exception:
                    pass

            # Trigger schedule compact
            trigger_text = ""
            cnl_sched = d.get("cnl_trigger_schedule")
            dq_sched = d.get("dq_trigger_schedule")
            oc_t = d.get("oc_target_pct")
            oc_f = d.get("oc_floor_pct")
            res_pct = d.get("initial_reserve_pct")

            parts = []
            if dq_sched:
                try:
                    import json as _json
                    sched = _json.loads(dq_sched) if isinstance(dq_sched, str) else dq_sched
                    if sched:
                        first = sched[0].get("threshold_pct", "?")
                        last = sched[-1].get("threshold_pct", "?")
                        parts.append(f"DQ {first}-{last}%")
                except Exception:
                    pass
            if oc_t:
                parts.append(f"OC↑{oc_t*100:.1f}%")
            if oc_f:
                parts.append(f"OC↓{oc_f*100:.1f}%")
            if res_pct:
                parts.append(f"Res {res_pct*100:.1f}%")
            trigger_text = "; ".join(parts) if parts else "—"

            wal_str = f"{d['wal']:.1f}y" if d.get("wal") else '<span style="color:#999">—</span>'

            row_class = ""
            if d["issuer"] == "CARMX":
                row_class = ' style="background:#FFF8E1"'
            elif "-N" in d["deal"]:
                row_class = ' style="background:#FBE9E7"'

            rows_html += f"""<tr{row_class}>
<td style="font-weight:600">{d['issuer']}</td>
<td>{d['deal']}</td>
<td>{cutoff}</td>
<td title="${ipb:,.0f}">{fm(ipb)}</td>
<td>{pf(d['aaa_pct'],1)}</td>
<td>{pf(d['aa_pct'],1)}</td>
<td>{pf(d['a_pct'],1)}</td>
<td>{pf(d['bbb_pct'],1)}</td>
<td>{pf(d['oc_pct'],1)}</td>
<td style="font-size:.6rem;max-width:120px;white-space:normal;line-height:1.2">{trigger_text}</td>
<td>{pf(d.get('consumer_wac'),2)}</td>
<td>{pf(d.get('cost_of_debt'),2)}</td>
<td>{pf(d.get('excess_spread_yr'),2)}</td>
<td>{wal_str}</td>
<td>{dollar_hover(d.get('total_excess_spread'), ipb)}</td>
<td>{dollar_hover(d.get('total_servicing_cost'), ipb)}</td>
<td>{dollar_hover(d.get('expected_loss_pct'), ipb)}</td>
<td>{pf_color(d.get('expected_residual'))}</td>
<td>{dollar_hover(d.get('actual_cum_interest_pct'), ipb)}</td>
<td>{dollar_hover(d.get('actual_cum_servicing_pct'), ipb)}</td>
<td>{dollar_hover(d.get('projected_loss_pct'), ipb)}</td>
<td>{pf_color(d.get('actual_residual'))}</td>
<td>{pf_color(d.get('variance'))}</td>
<td>{pf(d.get('pct_complete'),0) if d.get('pct_complete') is not None else '<span style="color:#999">—</span>'}</td>
<td>{trigger_badge(d.get('trigger_risk'))}</td>
</tr>\n"""
        return rows_html

    def _weighted_avg_row(deal_list, label):
        """Compute weighted-average summary row."""
        total_ipb = sum(d["initial_pool_balance"] for d in deal_list)
        if total_ipb == 0:
            return ""

        def wavg(key):
            vals = [(d.get(key), d["initial_pool_balance"]) for d in deal_list if d.get(key) is not None]
            if not vals:
                return None
            return sum(v * w for v, w in vals) / sum(w for _, w in vals)

        wa = {k: wavg(k) for k in [
            "aaa_pct", "aa_pct", "a_pct", "bbb_pct", "oc_pct",
            "consumer_wac", "cost_of_debt", "excess_spread_yr", "wal",
            "total_excess_spread", "total_servicing_cost", "expected_loss_pct",
            "expected_residual", "actual_cum_interest_pct", "actual_cum_servicing_pct",
            "projected_loss_pct", "actual_residual", "variance", "pct_complete",
        ]}

        wal_str = f"{wa['wal']:.1f}y" if wa.get("wal") else "—"
        return f"""<tr style="background:#E3F2FD;font-weight:700">
<td colspan="3">{label}</td>
<td>{fm(total_ipb)}</td>
<td>{pf(wa['aaa_pct'],1)}</td><td>{pf(wa['aa_pct'],1)}</td>
<td>{pf(wa['a_pct'],1)}</td><td>{pf(wa['bbb_pct'],1)}</td>
<td>{pf(wa['oc_pct'],1)}</td><td></td>
<td>{pf(wa['consumer_wac'],2)}</td><td>{pf(wa['cost_of_debt'],2)}</td>
<td>{pf(wa['excess_spread_yr'],2)}</td><td>{wal_str}</td>
<td>{pf(wa['total_excess_spread'],2)}</td><td>{pf(wa['total_servicing_cost'],2)}</td>
<td>{pf(wa['expected_loss_pct'],2)}</td><td>{pf_color(wa['expected_residual'])}</td>
<td>{pf(wa['actual_cum_interest_pct'],2)}</td><td>{pf(wa['actual_cum_servicing_pct'],2)}</td>
<td>{pf(wa['projected_loss_pct'],2)}</td><td>{pf_color(wa['actual_residual'])}</td>
<td>{pf_color(wa['variance'])}</td><td>{pf(wa['pct_complete'],0) if wa.get('pct_complete') else '—'}</td>
<td></td>
</tr>\n"""

    forecast_source = "Markov chain" if has_markov else "logistic regression"
    forecast_note = "" if has_markov else ' <span style="color:#F57F17;font-size:.6rem">(LR model — Markov pending)</span>'

    h = f"""<div style="padding:8px 12px">
<h2 style="font-size:1rem;margin-bottom:4px">Residual Economics — All Deals{forecast_note}</h2>
<p style="font-size:.7rem;color:#666;margin-bottom:8px">
Hover any % cell for dollar amount. Yellow rows = CarMax. Orange rows = Carvana non-prime.
Loss forecasts from {forecast_source} model. {'Markov model running — forecasts will update.' if not has_markov else ''}
</p>
</div>
<div class="tbl" style="max-height:70vh;overflow:auto">
<table style="font-size:.6rem">
<thead>
<tr style="position:sticky;top:0;z-index:2;background:#f5f5f5">
<th colspan="4" style="text-align:center;border-bottom:2px solid #1976D2">Identity</th>
<th colspan="5" style="text-align:center;border-bottom:2px solid #388E3C">Capital Structure (% init pool)</th>
<th style="text-align:center;border-bottom:2px solid #607D8B">Terms</th>
<th colspan="8" style="text-align:center;border-bottom:2px solid #FF9800">Initial Forecast (% orig bal)</th>
<th colspan="4" style="text-align:center;border-bottom:2px solid #7B1FA2">Realized / Projected</th>
<th colspan="3" style="text-align:center;border-bottom:2px solid #D32F2F">Variance &amp; Risk</th>
</tr>
<tr style="position:sticky;top:22px;z-index:2;background:#f5f5f5">
<th>Issuer</th><th>Deal</th><th>Cutoff</th><th>Orig Bal</th>
<th>AAA</th><th>AA</th><th>A</th><th>BBB</th><th>OC</th>
<th>Triggers / OC / Reserve</th>
<th>WAC</th><th>CoD</th><th>XS/yr</th><th>WAL</th>
<th>Tot XS</th><th>Svc</th><th>Exp Loss</th><th>Exp Resid</th>
<th>Act Int</th><th>Act Svc</th><th>Proj Loss</th><th>Act Resid</th>
<th>Var</th><th>%Done</th><th>Trig Risk</th>
</tr>
</thead>
<tbody>
"""

    # Main section: Prime + CarMax interleaved
    h += _build_table_rows(prime_and_carmax)

    # Summary rows
    if crvna_prime:
        h += _weighted_avg_row(crvna_prime, "Carvana Prime Avg")
    if carmx_deals:
        h += _weighted_avg_row(carmx_deals, "CarMax Avg")
    if prime_and_carmax:
        h += _weighted_avg_row(prime_and_carmax, "All Prime Avg")

    # Non-prime section
    if crvna_nonprime:
        h += f"""<tr><td colspan="25" style="background:#FFCCBC;text-align:center;font-weight:700;padding:6px">
Carvana Non-Prime</td></tr>\n"""
        h += _build_table_rows(crvna_nonprime)
        h += _weighted_avg_row(crvna_nonprime, "Carvana Non-Prime Avg")

    h += "</tbody></table></div>\n"

    # ── 9. Methodology writeup ───────────────────────────────────────────
    h += _generate_methodology_writeup()

    return h


def _generate_methodology_writeup():
    """Comprehensive methodology section for the economics tab."""

    h = """
<div style="padding:12px 16px;max-width:900px;margin:0 auto">
<h2 style="font-size:1.1rem;color:#1976D2;border-bottom:2px solid #1976D2;padding-bottom:4px;margin-top:24px">
Methodology: Markov Chain Loss Forecasting &amp; Residual Economics</h2>

<p style="font-size:.8rem;color:#333;line-height:1.6;margin:12px 0">
This section explains how we forecast lifetime credit losses and compute residual economics
for each auto-loan securitization. The audience is assumed to know basic statistics but not
Markov chains specifically. We provide enough detail that someone could reproduce the model
from this description alone.
</p>

<!-- ── 1. What is a Markov Chain ── -->
<h3 style="font-size:.95rem;color:#333;margin-top:20px">1. What is a Markov Chain?</h3>
<p style="font-size:.78rem;line-height:1.6;color:#444">
A Markov chain is a model where the future depends only on the <em>current state</em>, not
the full history. For auto loans, this means: if we know a loan is currently 2 payments
behind, the probability it goes to 3 payments behind next month depends only on that
"2 payments behind" status — not on whether it was current 6 months ago or always delinquent.
</p>
<p style="font-size:.78rem;line-height:1.6;color:#444">
<strong>Concrete example:</strong> A loan that is 60 days past due has (say) a 35% chance of
curing to 30 days past due next month, a 40% chance of staying at 60 days, a 20% chance of
going to 90 days, and a 5% chance of paying off entirely. These probabilities are the
"transition matrix" — the core of the model.
</p>

<!-- ── 2. State Diagram ── -->
<h3 style="font-size:.95rem;color:#333;margin-top:20px">2. Delinquency States</h3>
<p style="font-size:.78rem;line-height:1.6;color:#444;margin-bottom:8px">
Every loan, every month, occupies exactly one state:
</p>

<!-- CSS State Diagram -->
<div style="overflow-x:auto;padding:8px 0">
<div style="display:flex;align-items:center;gap:4px;min-width:700px;font-size:.7rem">
<div style="background:#C8E6C9;border:2px solid #388E3C;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:#2E7D32">Current</div>
<div style="color:#555;font-size:.6rem">0 DPD</div>
</div>
<div style="color:#888">→</div>
<div style="background:#FFF9C4;border:2px solid #F9A825;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:#F57F17">1 Pmt</div>
<div style="color:#555;font-size:.6rem">30 DPD</div>
</div>
<div style="color:#888">→</div>
<div style="background:#FFE0B2;border:2px solid #FF9800;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:#E65100">2 Pmt</div>
<div style="color:#555;font-size:.6rem">60 DPD</div>
</div>
<div style="color:#888">→</div>
<div style="background:#FFCCBC;border:2px solid #FF5722;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:#BF360C">3 Pmt</div>
<div style="color:#555;font-size:.6rem">90 DPD</div>
</div>
<div style="color:#888">→</div>
<div style="background:#FFCDD2;border:2px solid #E53935;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:#C62828">4 Pmt</div>
<div style="color:#555;font-size:.6rem">120 DPD</div>
</div>
<div style="color:#888">→</div>
<div style="background:#EF9A9A;border:2px solid #C62828;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:#B71C1C">5+ Pmt</div>
<div style="color:#555;font-size:.6rem">150+ DPD</div>
</div>
<div style="color:#888">→</div>
<div style="background:#B71C1C;border:2px solid #7f0000;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px">
<div style="font-weight:700;color:white">Default</div>
<div style="color:#ffcdd2;font-size:.6rem">Absorbing</div>
</div>
</div>
<div style="display:flex;justify-content:flex-start;margin-top:4px;margin-left:0">
<div style="background:#E3F2FD;border:2px solid #1976D2;border-radius:8px;padding:8px 10px;text-align:center;min-width:65px;font-size:.7rem">
<div style="font-weight:700;color:#1565C0">Payoff</div>
<div style="color:#555;font-size:.6rem">Absorbing</div>
</div>
<div style="color:#888;font-size:.7rem;padding:8px 6px">← Any state can transition here (prepayment or maturity)</div>
</div>
</div>

<p style="font-size:.78rem;line-height:1.6;color:#444;margin-top:8px">
<strong>Default</strong> and <strong>Payoff</strong> are <em>absorbing states</em> — once a loan
enters, it stays. All other states are <em>transient</em>: a loan can move forward (deeper
delinquency), backward (cure), or sideways (stay). At each monthly transition, the model
assigns a probability to each possible next state.
</p>

<!-- ── 3. Cell Key ── -->
<h3 style="font-size:.95rem;color:#333;margin-top:20px">3. Segmentation Cells</h3>
<p style="font-size:.78rem;line-height:1.6;color:#444">
Not all loans behave the same. A 780-FICO borrower with 60% LTV behaves very differently
from a 580-FICO borrower at 130% LTV. The model segments loans into cells based on
characteristics that empirically predict transition behavior:
</p>
<div style="overflow-x:auto">
<table style="font-size:.72rem;max-width:600px;margin:8px 0">
<thead><tr><th>Dimension</th><th>Buckets</th><th>Why It Matters</th></tr></thead>
<tbody>
<tr><td><strong>FICO score</strong></td><td>&lt;580, 580-619, 620-659, 660-699, 700-739, 740+</td>
<td>Primary credit-quality signal</td></tr>
<tr><td><strong>LTV ratio</strong></td><td>&lt;80%, 80-99%, 100-119%, 120%+</td>
<td>Negative equity drives strategic default</td></tr>
<tr><td><strong>Original term</strong></td><td>≤48mo, 49-60mo, 61-72mo, 73+mo</td>
<td>Longer terms = slower equity build</td></tr>
<tr><td><strong>Loan age</strong></td><td>0-6, 7-12, 13-24, 25-36, 37+mo</td>
<td>Default hazard peaks in months 12-24</td></tr>
<tr><td><strong>Delinquency status</strong></td><td>Current, 1-pmt, 2-pmt, 3-pmt, 4-pmt, 5+pmt</td>
<td>The Markov state itself</td></tr>
<tr><td><strong>Modification flag</strong></td><td>Modified / Not modified</td>
<td>Modified loans have different cure rates</td></tr>
</tbody></table>
</div>
<p style="font-size:.78rem;line-height:1.6;color:#444">
Each unique combination of these dimensions forms a "cell." A cell might be: "FICO 620-659,
LTV 100-119%, 61-72mo term, age 13-24mo, currently 1 payment behind, not modified." The model
estimates a separate transition matrix for each populated cell.
</p>

<!-- ── 4. How Transitions Are Estimated ── -->
<h3 style="font-size:.95rem;color:#333;margin-top:20px">4. Estimating Transition Probabilities</h3>
<p style="font-size:.78rem;line-height:1.6;color:#444">
For each cell, we count what happened to similar loans in the next month:
</p>
<div style="background:#F5F5F5;border-left:3px solid #1976D2;padding:8px 12px;margin:8px 0;font-size:.75rem;font-family:monospace;line-height:1.5">
Cell: FICO 620-659, LTV 100-119%, 61-72mo, age 13-24, status = 2 payments behind<br>
Observed loans in this cell: 2,847<br>
<br>
Next-month outcomes:<br>
&nbsp;&nbsp;Cured to Current: &nbsp;142 &nbsp;(5.0%)<br>
&nbsp;&nbsp;Improved to 1-pmt: &nbsp;498 &nbsp;(17.5%)<br>
&nbsp;&nbsp;Stayed at 2-pmt: &nbsp;&nbsp;1,139 (40.0%)<br>
&nbsp;&nbsp;Worsened to 3-pmt: &nbsp;854 &nbsp;(30.0%)<br>
&nbsp;&nbsp;Defaulted: &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;171 &nbsp;(6.0%)<br>
&nbsp;&nbsp;Paid off: &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;43 &nbsp;&nbsp;(1.5%)
</div>
<p style="font-size:.78rem;line-height:1.6;color:#444">
<strong>Each loan counts equally</strong> — we do not weight by balance. The training dataset spans
<strong>3.5 million loans across 53 deals</strong> (16 Carvana + 37 CarMax), giving dense coverage
of most cells. Cells with fewer than 30 observations borrow strength from adjacent cells
(e.g., the nearest FICO bucket) via shrinkage.
</p>

<!-- ── Example Transition Heatmap ── -->
<h3 style="font-size:.95rem;color:#333;margin-top:20px">Example: Transition Probability Heatmap</h3>
<p style="font-size:.78rem;line-height:1.6;color:#444;margin-bottom:8px">
This shows a stylized transition matrix for a typical prime borrower cell (FICO 700+, LTV &lt;100%,
age 7-12 months). Each row is the current state; each column is the next-month state.
Darker cells = higher probability.
</p>
<div style="overflow-x:auto">
<table style="font-size:.65rem;max-width:650px;margin:8px 0;text-align:center">
<thead><tr><th style="min-width:60px">From \\ To</th>
<th>Current</th><th>1-Pmt</th><th>2-Pmt</th><th>3-Pmt</th><th>4-Pmt</th><th>5+</th>
<th>Default</th><th>Payoff</th></tr></thead>
<tbody>
<tr><td style="font-weight:600">Current</td>
<td style="background:#1B5E20;color:white">93.5%</td>
<td style="background:#A5D6A7">3.2%</td>
<td style="background:#E8F5E9">0.1%</td>
<td style="background:#FFF">0.0%</td>
<td style="background:#FFF">0.0%</td>
<td style="background:#FFF">0.0%</td>
<td style="background:#FFEBEE">0.1%</td>
<td style="background:#BBDEFB">3.1%</td></tr>
<tr><td style="font-weight:600">1-Pmt</td>
<td style="background:#66BB6A;color:white">42.0%</td>
<td style="background:#FFD54F">35.0%</td>
<td style="background:#FFB74D">15.0%</td>
<td style="background:#FFCCBC">3.0%</td>
<td style="background:#FFF">0.5%</td>
<td style="background:#FFF">0.0%</td>
<td style="background:#EF9A9A">2.5%</td>
<td style="background:#BBDEFB">2.0%</td></tr>
<tr><td style="font-weight:600">2-Pmt</td>
<td style="background:#A5D6A7">18.0%</td>
<td style="background:#C8E6C9">12.0%</td>
<td style="background:#FFD54F">35.0%</td>
<td style="background:#FFB74D">22.0%</td>
<td style="background:#FFCCBC">4.0%</td>
<td style="background:#FFF">1.0%</td>
<td style="background:#E57373;color:white">6.5%</td>
<td style="background:#BBDEFB">1.5%</td></tr>
<tr><td style="font-weight:600">3-Pmt</td>
<td style="background:#C8E6C9">8.0%</td>
<td style="background:#E8F5E9">5.0%</td>
<td style="background:#FFF9C4">10.0%</td>
<td style="background:#FFD54F">30.0%</td>
<td style="background:#FFB74D">25.0%</td>
<td style="background:#FFCCBC">5.0%</td>
<td style="background:#E53935;color:white">16.0%</td>
<td style="background:#BBDEFB">1.0%</td></tr>
<tr><td style="font-weight:600">4-Pmt</td>
<td style="background:#E8F5E9">3.0%</td>
<td style="background:#FFF">2.0%</td>
<td style="background:#FFF">3.0%</td>
<td style="background:#FFF9C4">8.0%</td>
<td style="background:#FFD54F">28.0%</td>
<td style="background:#FFB74D">20.0%</td>
<td style="background:#C62828;color:white">35.0%</td>
<td style="background:#BBDEFB">1.0%</td></tr>
<tr><td style="font-weight:600">5+ Pmt</td>
<td style="background:#FFF">1.0%</td>
<td style="background:#FFF">1.0%</td>
<td style="background:#FFF">1.0%</td>
<td style="background:#FFF">2.0%</td>
<td style="background:#FFF9C4">5.0%</td>
<td style="background:#FFB74D">20.0%</td>
<td style="background:#B71C1C;color:white">69.0%</td>
<td style="background:#BBDEFB">1.0%</td></tr>
</tbody></table>
</div>
<p style="font-size:.72rem;color:#888;margin-top:2px">
Values are illustrative for a prime-quality cell. Actual matrices vary by cell and are
estimated from observed data.
</p>

<!-- ── 5. Bayesian Calibration ── -->
<h3 style="font-size:.95rem;color:#333;margin-top:20px">5. Bayesian Calibration to Deal Performance</h3>
<p style="font-size:.78rem;line-height:1.6;color:#444">
The base transition matrices come from pooled historical data across all deals. But each deal
has its own personality — origination standards shift, used-car prices fluctuate, the economy
evolves. <strong>Bayesian calibration</strong> adjusts the base matrices using that deal's
actual performance so far.
</p>
<p style="font-size:.78rem;line-height:1.6;color:#444">
<strong>How it works:</strong> We model the deal-specific loss multiplier as a log-normal
random variable. The prior (before seeing data) assumes the deal behaves like the historical
average. As we observe actual defaults, the posterior shifts toward the deal's true experience.
</p>

<div style="background:#F5F5F5;border-left:3px solid #FF9800;padding:10px 14px;margin:10px 0;font-size:.75rem;line-height:1.6">
<strong>Calibration parameters:</strong><br>
&bull; Prior: log-normal with mean = 1.0 (historical average) and &sigma;<sub>prior</sub> = 0.30<br>
&bull; Credibility weight = realized defaults ($) / total pool balance ($)<br>
&bull; Posterior multiplier = (prior &times; (1 - credibility)) + (observed_rate / predicted_rate &times; credibility)<br>
&bull; All transition-to-default probabilities in the matrix are scaled by this multiplier
</div>

<h4 style="font-size:.85rem;color:#555;margin-top:12px">Worked Example: CRVNA 2022-P1</h4>
<div style="background:#FAFAFA;border:1px solid #E0E0E0;border-radius:6px;padding:10px 14px;margin:8px 0;font-size:.72rem;line-height:1.7;font-family:monospace">
Base model predicted lifetime CNL: 4.27% of original pool<br>
Realized CNL so far (48 months): 2.64% ($27.9M on $1,054M pool)<br>
Pool factor: 16.3% remaining<br>
<br>
Credibility weight = $27.9M / $1,054M = 0.026<br>
Observed / predicted ratio = 2.64% / 4.27% = 0.618<br>
<br>
Posterior multiplier = (1.0 &times; 0.974) + (0.618 &times; 0.026) = 0.990<br>
<br>
Interpretation: With only 16.3% of the pool remaining, the model is 97.4% reliant on the<br>
prior and 2.6% on observed data. The slight underperformance vs forecast barely moves the<br>
dial because most losses have already been realized. The calibrated projected CNL is ~6.6%<br>
(realized 2.64% + remaining losses on the 16.3% still outstanding, scaled by 0.990).
</div>

<!-- ── 6. At-Issuance Forecast ── -->
<h3 style="font-size:.95rem;color:#333;margin-top:20px">6. At-Issuance Forecast</h3>
<p style="font-size:.78rem;line-height:1.6;color:#444">
At deal closing, every loan starts in the "Current" state at age 0. The model steps the
entire pool forward month by month through the transition matrices:
</p>
<ol style="font-size:.78rem;line-height:1.6;color:#444;padding-left:20px">
<li>Start: all loans Current, age 0</li>
<li>Each month: apply the cell-specific transition matrix for that loan's characteristics and age</li>
<li>Loans that transition to "Default" are removed and their balance counted as a loss (net of estimated recovery)</li>
<li>Loans that transition to "Payoff" are removed (prepayment or maturity)</li>
<li>Continue until the pool is fully liquidated (all loans in Default or Payoff)</li>
<li>The cumulative default balance divided by the original pool balance = <strong>at-issuance CNL forecast</strong></li>
</ol>
<p style="font-size:.78rem;line-height:1.6;color:#444">
<strong>No calibration is applied at issuance</strong> — the deal has no performance history yet.
This is a purely forward-looking forecast based on the pool's initial characteristics.
</p>

<!-- ── 7. In-Progress Forecast ── -->
<h3 style="font-size:.95rem;color:#333;margin-top:20px">7. In-Progress (Current) Forecast</h3>
<p style="font-size:.78rem;line-height:1.6;color:#444">
For deals with performance history, the forecast is updated monthly:
</p>
<ol style="font-size:.78rem;line-height:1.6;color:#444;padding-left:20px">
<li>Start from the <em>current</em> state of every surviving loan (using latest servicer report)</li>
<li>Apply the <strong>calibrated</strong> transition matrices (base &times; posterior multiplier)</li>
<li>Project remaining defaults forward until pool liquidation</li>
<li>Total projected CNL = <strong>realized losses to date + projected remaining losses</strong></li>
</ol>
<p style="font-size:.78rem;line-height:1.6;color:#444">
As a deal seasons, the in-progress forecast converges toward realized performance because
fewer loans remain to default and the calibration multiplier increasingly reflects observed data.
</p>

<!-- ── 8. Residual Profit Calculation ── -->
<h3 style="font-size:.95rem;color:#333;margin-top:20px">8. Residual Profit Calculation</h3>
<p style="font-size:.78rem;line-height:1.6;color:#444">
The residual profit to the equity holder (the issuer or any residual certificate buyer) is
the excess of interest income over debt service, servicing costs, and credit losses. All
figures below are expressed as a percentage of the original pool balance.
</p>

<div style="overflow-x:auto">
<table style="font-size:.72rem;max-width:650px;margin:8px 0">
<thead><tr><th style="min-width:200px">Line Item</th><th>Formula</th></tr></thead>
<tbody>
<tr><td>Consumer WAC (a)</td><td>Weighted average coupon of underlying loans at origination</td></tr>
<tr><td>Cost of Debt (b)</td><td>Weighted average coupon of all note tranches</td></tr>
<tr><td>Excess Spread / Year (c)</td><td>= a - b</td></tr>
<tr><td>Weighted Average Life (d)</td><td>From Markov projection or balance amortization</td></tr>
<tr><td>Total Excess Spread (e)</td><td>= c &times; d</td></tr>
<tr><td>Total Servicing Cost (f)</td><td>= annual servicing fee % &times; d</td></tr>
<tr><td>Expected Losses (g)</td><td>= model-projected lifetime CNL %</td></tr>
<tr><td style="font-weight:700;color:#1976D2">Expected Residual Profit (h)</td>
<td style="font-weight:700">= e - f - g</td></tr>
</tbody></table>
</div>

<h4 style="font-size:.85rem;color:#555;margin-top:12px">Worked Example: Mature Deal (CRVNA 2021-P1)</h4>
<div style="background:#FAFAFA;border:1px solid #E0E0E0;border-radius:6px;padding:10px 14px;margin:8px 0;font-size:.72rem;line-height:1.7;font-family:monospace">
Original pool balance: $415M<br>
Consumer WAC: 8.18% | Cost of Debt: 0.55% | Excess spread/yr: 7.64%<br>
Estimated WAL: ~2.5 years<br>
<br>
Total excess spread: 7.64% &times; 2.5 = 19.09%<br>
Total servicing cost: 0.57% &times; 2.5 = 1.42%<br>
Expected losses (model): 5.20%<br>
<br>
<strong>Expected residual profit: 19.09% - 1.42% - 5.20% = 12.47%</strong> ($51.7M on $415M pool)<br>
<br>
Actual cumulative interest earned: 16.25% of original pool ($67.4M)<br>
Actual cumulative servicing: 2.85%<br>
Realized + projected losses: 4.58%<br>
<br>
<strong>Actual residual profit: 16.25% - 2.85% - 4.58% = 8.82%</strong> ($36.6M)<br>
Variance from forecast: -3.66% (faster prepayments shortened WAL, reducing total interest)
</div>

<h4 style="font-size:.85rem;color:#555;margin-top:12px">Worked Example: In-Progress Deal (CRVNA 2024-P3)</h4>
<div style="background:#FAFAFA;border:1px solid #E0E0E0;border-radius:6px;padding:10px 14px;margin:8px 0;font-size:.72rem;line-height:1.7;font-family:monospace">
Original pool balance: $639M (cutoff Aug-2024, ~18 months seasoned)<br>
Consumer WAC: 13.69% | Cost of Debt: 4.51% | Excess spread/yr: 9.17%<br>
Estimated WAL: ~2.8 years<br>
<br>
Total excess spread: 9.17% &times; 2.8 = 25.69%<br>
Total servicing cost: 0.59% &times; 2.8 = 1.65%<br>
Expected losses (model): 5.93%<br>
<br>
<strong>Expected residual profit: 25.69% - 1.65% - 5.93% = 18.10%</strong><br>
<br>
Actual interest so far: 15.64% | Actual servicing: 0.88% | Realized losses: 1.99%<br>
Pool factor: ~54% remaining — still early<br>
<br>
<strong>Actual residual so far: 15.64% - 0.88% - 1.99% = 12.77%</strong><br>
Variance vs expected: -5.33% (but deal is only ~46% complete — variance will narrow as<br>
remaining interest is collected)
</div>

<!-- ── 9. Data Sources ── -->
<h3 style="font-size:.95rem;color:#333;margin-top:20px">9. Data Sources</h3>
<div style="overflow-x:auto">
<table style="font-size:.72rem;max-width:650px;margin:8px 0">
<thead><tr><th>Source</th><th>Filing Type</th><th>What We Extract</th></tr></thead>
<tbody>
<tr><td>SEC EDGAR</td><td>424(b)(5) Prospectus</td>
<td>Capital structure, note coupons, triggers, servicing fee, pool characteristics</td></tr>
<tr><td>SEC EDGAR</td><td>10-D Monthly Report</td>
<td>Pool performance: collections, losses, delinquencies, note balances, OC levels</td></tr>
<tr><td>SEC EDGAR</td><td>ABS-EE (XML)</td>
<td>Loan-level data: FICO, LTV, term, rate, balance, status, geography</td></tr>
</tbody></table>
</div>
<p style="font-size:.78rem;line-height:1.6;color:#444">
<strong>Dataset:</strong> ~3.5 million loans across 53 deals (16 Carvana + 37 CarMax).
Carvana deals span 2020-P1 through 2025-P4. CarMax deals span 2014-1 through 2025-3.
All data is public, sourced directly from SEC EDGAR with no third-party intermediary.
</p>

<!-- ── 10. Limitations ── -->
<h3 style="font-size:.95rem;color:#333;margin-top:20px">10. Limitations &amp; Caveats</h3>
<ul style="font-size:.78rem;line-height:1.6;color:#444;padding-left:20px">
<li><strong>Stationarity assumption:</strong> The model assumes transition probabilities
estimated from historical data apply to the future. A severe recession, sudden used-car
price collapse, or regulatory change could invalidate this. The model has no macro-economic
inputs and cannot forecast regime changes.</li>
<li><strong>Vintage effects:</strong> Origination standards shift over time. 2021 non-prime
originations (during the used-car bubble) behave very differently from 2024 originations.
Cell-level segmentation captures some of this via FICO/LTV, but not all vintage-specific
factors (e.g., inflated vehicle values that aren't visible in the LTV ratio).</li>
<li><strong>Prospectus parsing:</strong> Capital structure and deal terms are extracted
algorithmically from SEC 424(b)(5) filings. These prospectuses vary in format across
issuers and vintages. Some fields (particularly CNL trigger schedules and OC step-up
schedules) may be incomplete or approximate. Manual spot-checks have been performed but
exhaustive validation has not.</li>
<li><strong>Recovery rates:</strong> The model applies historical average recovery rates
(~40% of chargeoff amount). Actual recoveries depend on used-car market conditions at
the time of liquidation, which the model does not forecast.</li>
<li><strong>Loan-level data availability:</strong> ABS-EE loan-level data is available only
from the point each deal was issued. Pre-securitization performance (origination to
securitization cutoff) is not observed.</li>
<li><strong>Small-cell estimation:</strong> Some cells (e.g., very high FICO + very high LTV)
have limited observations. These borrow from adjacent cells, which may introduce bias if
the adjacent cell is not truly representative.</li>
</ul>

<h3 style="font-size:.95rem;color:#333;margin-top:20px">Reproducibility</h3>
<p style="font-size:.78rem;line-height:1.6;color:#444">
<strong>To reproduce this model, you need:</strong>
</p>
<ol style="font-size:.78rem;line-height:1.6;color:#444;padding-left:20px">
<li>ABS-EE loan-level XML files from SEC EDGAR for all Carvana (CRVNA) and CarMax (CARMX) auto ABS deals</li>
<li>10-D monthly servicer reports for pool-level performance data</li>
<li>424(b)(5) prospectus supplements for capital structure and deal terms</li>
<li>Segment loans into cells by: FICO (6 buckets), LTV (4 buckets), original term (4 buckets),
loan age (5 buckets), delinquency status (7 states including Default and Payoff), modification flag (2 levels)</li>
<li>For each cell, count monthly state transitions across all observed loan-months. Each loan gets equal weight.</li>
<li>Minimum cell size: 30 observations. Below that, borrow from the nearest FICO bucket.</li>
<li>Bayesian calibration: log-normal prior with &mu; = 0, &sigma; = 0.30 (i.e., prior multiplier = 1.0).
Credibility = realized_defaults_$ / total_pool_balance_$. Posterior multiplier =
prior &times; (1 - credibility) + (observed/predicted) &times; credibility.</li>
<li>Forward simulation: step each surviving loan monthly through its cell-appropriate transition matrix until
all loans reach an absorbing state (Default or Payoff).</li>
<li>Loss amount = defaulted balance &times; (1 - recovery rate). Historical average recovery rate: 39.8%.</li>
</ol>

<p style="font-size:.72rem;color:#888;margin-top:16px;padding-top:8px;border-top:1px solid #E0E0E0">
Model last updated: April 2026. Data as of latest available 10-D filings on SEC EDGAR.
Questions: clifford.sosin@casinvestmentpartners.com
</p>
</div>
"""
    return h


def main():
    global _chart_id
    _chart_id = 0

    deal_contents = {}
    for deal in DASHBOARD_DEALS:
        logger.info(f"Generating {deal}...")
        result = generate_deal_content(deal)
        if result:
            deal_contents[deal] = result

    if not deal_contents:
        logger.error("No deals with data found.")
        return

    # Generate CarMax per-deal content (only if the CarMax DB is available)
    carmax_deal_contents = {}
    if carmax_available():
        for deal in CARMAX_DEALS:
            logger.info(f"Generating CARMX {deal}...")
            try:
                result = generate_carmax_deal_content(deal)
            except Exception as e:
                logger.error(f"[CARMX {deal}] Failed: {e}")
                result = None
            if result:
                carmax_deal_contents[deal] = result
    else:
        logger.info("CarMax DB not found — skipping CarMax deal tabs.")

    # Generate comparison sections
    logger.info("Generating Prime comparison...")
    prime_html = generate_comparison_content(
        [d for d in PRIME_DEALS if d in deal_contents], "Prime Deals")
    logger.info("Generating Non-Prime comparison...")
    nonprime_html = generate_comparison_content(
        [d for d in NONPRIME_DEALS if d in deal_contents], "Non-Prime Deals")

    carmax_prime_html = ""
    cross_issuer_html = ""
    if carmax_available() and carmax_deal_contents:
        logger.info("Generating CarMax Prime comparison...")
        carmax_prime_html = generate_carmax_comparison_content(
            [d for d in CARMAX_PRIME_DEALS if d in carmax_deal_contents],
            "CarMax Prime Deals")
        logger.info("Generating cross-issuer (Carvana vs CarMax) comparison...")
        cross_issuer_html = generate_cross_issuer_comparison()

    # Generate default model analysis
    logger.info("Generating Default Model analysis...")
    model_html = generate_model_content()

    # Generate residual economics tab (landing page)
    logger.info("Generating Residual Economics tab...")
    economics_html = generate_economics_tab()

    # Build deal selector dropdown with comparison entries at top
    first_deal = list(deal_contents.keys())[0]
    options = '<option value="__economics__" selected>--- Residual Economics ---</option>\n'
    options += '<option value="__model__">--- Default Model ---</option>\n'
    options += '<option value="__prime__">--- Prime Comparison (Carvana) ---</option>\n'
    options += '<option value="__nonprime__">--- Non-Prime Comparison (Carvana) ---</option>\n'
    if carmax_prime_html:
        options += '<option value="__carmax_prime__">--- CarMax Prime Comparison ---</option>\n'
    if cross_issuer_html:
        options += '<option value="__cross__">--- Carvana vs CarMax — Prime ---</option>\n'
    options += '<option disabled>──────────────────</option>\n'
    options += "\n".join(
        f'<option value="{d}">Carvana {d}</option>'
        for d in deal_contents)
    # CarMax per-deal entries — prefix "cm_" in the value to keep them in a
    # disjoint namespace from Carvana deal IDs.
    if carmax_deal_contents:
        options += "\n" + "\n".join(
            f'<option value="cm_{d}">CarMax {d}</option>'
            for d in carmax_deal_contents)
    deal_selector = f'<div class="deal-select"><select id="dealSelect" onchange="switchDeal(this.value)">{options}</select></div>'

    # Build per-deal content divs
    all_deal_html = ""
    # Economics tab shown by default (landing page)
    all_deal_html += f'<div id="deal-__economics__" class="deal-block" style="display:block">\n{economics_html}\n</div>\n'
    # Add model and comparison sections (hidden by default)
    all_deal_html += f'<div id="deal-__model__" class="deal-block" style="display:none">\n{model_html}\n</div>\n'
    all_deal_html += f'<div id="deal-__prime__" class="deal-block" style="display:none">\n{prime_html}\n</div>\n'
    all_deal_html += f'<div id="deal-__nonprime__" class="deal-block" style="display:none">\n{nonprime_html}\n</div>\n'
    if carmax_prime_html:
        all_deal_html += f'<div id="deal-__carmax_prime__" class="deal-block" style="display:none">\n{carmax_prime_html}\n</div>\n'
    if cross_issuer_html:
        all_deal_html += f'<div id="deal-__cross__" class="deal-block" style="display:none">\n{cross_issuer_html}\n</div>\n'
    # Add individual deal sections (all hidden — economics tab is default)
    for deal, (metrics, tabs) in deal_contents.items():
        all_deal_html += f'<div id="deal-{deal}" class="deal-block" style="display:none">\n{metrics}\n{tabs}\n</div>\n'
    # CarMax per-deal sections. Div id prefix matches the option value above.
    for deal, (metrics, tabs) in carmax_deal_contents.items():
        all_deal_html += (
            f'<div id="deal-cm_{deal}" class="deal-block" style="display:none">\n'
            f'<h2 style="padding:8px 12px 0;font-size:1rem;color:#333">'
            f'CarMax Auto Owner Trust {deal}</h2>\n'
            f'{metrics}\n{tabs}\n</div>\n'
        )

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Carvana ABS Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f5;color:#212121}}
header{{background:#1976D2;color:white;padding:12px 16px;position:sticky;top:0;z-index:100;display:flex;align-items:center;justify-content:space-between}}
header h1{{font-size:1.1rem;font-weight:600}}
.deal-select{{padding:4px 12px}}
.deal-select select{{font-size:.9rem;padding:6px 10px;border-radius:6px;border:1px solid #ccc;width:100%;max-width:300px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:6px;padding:8px 12px}}
.metric{{background:white;border-radius:8px;padding:8px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.mv{{font-size:1.1rem;font-weight:700;color:#1976D2}}.ml{{font-size:.65rem;color:#666;margin-top:2px}}
.tabs{{display:flex;flex-wrap:wrap;gap:4px;padding:6px 12px;position:sticky;top:44px;z-index:99;background:#f5f5f5}}
.tab{{padding:5px 10px;border:1px solid #ccc;border-radius:6px;background:white;cursor:pointer;font-size:.75rem}}
.tab.active{{background:#1976D2;color:white;border-color:#1976D2}}
.tc{{padding:0 12px 12px}}
.tbl{{overflow-x:auto;margin:8px 0}}
table{{width:100%;border-collapse:collapse;font-size:.7rem;background:white;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
th{{background:#f5f5f5;padding:5px 6px;text-align:left;border-bottom:2px solid #ddd;white-space:nowrap}}
td{{padding:4px 6px;border-bottom:1px solid #eee;white-space:nowrap}}
tr:last-child td{{font-weight:700;border-top:2px solid #ddd}}
table.compare tr:last-child td{{font-weight:normal;border-top:none}}
h3{{font-size:.85rem;color:#333;margin:10px 0 4px;padding:0 4px}}
footer{{text-align:center;padding:12px;color:#999;font-size:.65rem}}
@media(max-width:600px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.mv{{font-size:.95rem}}.tab{{font-size:.65rem;padding:4px 6px}}}}
</style></head><body>
<header><h1>Carvana ABS Dashboard</h1></header>
{deal_selector}
{all_deal_html}
<footer>Data from SEC EDGAR | Generated {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</footer>
<script>
function showTab(id,btn){{
    // Hide all tabs in current deal, show selected
    var deal = btn.closest('.deal-block');
    deal.querySelectorAll('.tc').forEach(e=>e.style.display='none');
    deal.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));
    document.getElementById(id).style.display='block';
    btn.classList.add('active');
    setTimeout(()=>window.dispatchEvent(new Event('resize')),100);
}}
function switchDeal(deal){{
    document.querySelectorAll('.deal-block').forEach(e=>e.style.display='none');
    document.getElementById('deal-'+deal).style.display='block';
    setTimeout(()=>window.dispatchEvent(new Event('resize')),100);
}}
</script>
</body></html>"""

    out = os.path.join(OUT_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    logger.info(f"Dashboard: {out} ({os.path.getsize(out)/1024:.0f} KB, {len(deal_contents)} deals)")


if __name__ == "__main__":
    main()
