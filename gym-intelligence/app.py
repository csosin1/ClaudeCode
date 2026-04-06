"""Streamlit web UI for gym intelligence tool.

Deployed behind nginx at /gym-intelligence/ — Streamlit's server.baseUrlPath
is set via CLI flag in the systemd unit (--server.baseUrlPath=/gym-intelligence).
"""

import csv
import io
import json
import os
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# .env loading — find the .env file (works in /opt/gym-intelligence/ or dev)
# ---------------------------------------------------------------------------
ENV_PATH = Path("/opt/gym-intelligence/.env")
if not ENV_PATH.exists():
    # Fallback to local .env for development
    ENV_PATH = Path(__file__).parent / ".env"


def _load_env():
    """Load key=value pairs from .env file into os.environ."""
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ[key.strip()] = value.strip()


def _save_env_key(key: str, value: str):
    """Write or update a single key in the .env file."""
    lines = []
    found = False
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped == f"{key}=":
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    # Ensure parent directory exists (for dev mode)
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(lines) + "\n")
    os.environ[key] = value


def _get_api_key() -> str:
    """Return the current ANTHROPIC_API_KEY or empty string."""
    _load_env()
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


# Load env on startup
_load_env()

# ---------------------------------------------------------------------------
# Lazy imports for heavy dependencies that may not be installed yet
# ---------------------------------------------------------------------------
try:
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
except ImportError:
    pd = None
    px = None
    go = None

import streamlit as st

from db import COUNTRY_NAMES, get_connection, init_db

st.set_page_config(
    page_title="Gym Intelligence - Basic-Fit Competitive Tracker",
    page_icon="🏋️",
    layout="centered",
)

init_db()

# ---------------------------------------------------------------------------
# Navigation — include Setup page
# Default to Setup if API key isn't configured yet (first-run experience)
# ---------------------------------------------------------------------------
PAGES = ["Market Overview", "Chain Explorer", "Competitive Analysis", "Admin / Refresh", "Setup"]
_default_page = "Setup" if not _get_api_key() else "Market Overview"
page = st.selectbox(
    "Navigate",
    PAGES,
    index=PAGES.index(_default_page),
    label_visibility="collapsed",
)

# ---------------------------------------------------------------------------
# Show API key warning on non-Setup pages if key is missing
# ---------------------------------------------------------------------------
if page != "Setup" and not _get_api_key():
    st.warning(
        "ANTHROPIC_API_KEY is not set. AI-powered features (classification, analysis) "
        "will not work. Go to the **Setup** page to configure it."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_snapshot_dates():
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT snapshot_date FROM snapshots ORDER BY snapshot_date DESC"
    ).fetchall()
    conn.close()
    return [r["snapshot_date"] for r in rows]


@st.cache_data(ttl=300)
def load_market_data(snapshot_date: str, country: str, min_locations: int):
    conn = get_connection()
    country_filter = ""
    params = [snapshot_date]
    if country != "All Europe":
        country_filter = "AND s.country = ?"
        params.append(country)

    rows = conn.execute(f"""
        SELECT c.canonical_name, c.competitive_classification, c.price_tier,
               c.normalized_18mo_cost, c.membership_model,
               SUM(s.location_count) as total_locations
        FROM snapshots s
        JOIN chains c ON s.chain_id = c.id
        WHERE s.snapshot_date = ? {country_filter}
          AND c.competitive_classification = 'direct_competitor'
        GROUP BY c.id
        ORDER BY total_locations DESC
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@st.cache_data(ttl=300)
def load_qoq_data(current_date: str, previous_date: str, country: str):
    conn = get_connection()
    country_filter = ""
    params = [current_date, previous_date]
    if country != "All Europe":
        country_filter = "AND s.country = ?"
        params.extend([country, country])

    rows = conn.execute(f"""
        SELECT
            c.canonical_name,
            COALESCE(curr.total, 0) as current_count,
            COALESCE(prev.total, 0) as previous_count
        FROM chains c
        LEFT JOIN (
            SELECT chain_id, SUM(location_count) as total
            FROM snapshots s
            WHERE snapshot_date = ? {country_filter}
            GROUP BY chain_id
        ) curr ON curr.chain_id = c.id
        LEFT JOIN (
            SELECT chain_id, SUM(location_count) as total
            FROM snapshots s
            WHERE snapshot_date = ? {country_filter.replace('?', '?')}
            GROUP BY chain_id
        ) prev ON prev.chain_id = c.id
        WHERE c.competitive_classification = 'direct_competitor'
          AND (COALESCE(curr.total, 0) > 0 OR COALESCE(prev.total, 0) > 0)
        ORDER BY COALESCE(curr.total, 0) DESC
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@st.cache_data(ttl=300)
def load_chains_list(min_locations: int):
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, canonical_name, location_count, competitive_classification
        FROM chains
        WHERE location_count >= ?
        ORDER BY location_count DESC
    """, (min_locations,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@st.cache_data(ttl=300)
def load_chain_detail(chain_name: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM chains WHERE canonical_name = ?", (chain_name,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


@st.cache_data(ttl=300)
def load_chain_snapshots(chain_name: str):
    conn = get_connection()
    rows = conn.execute("""
        SELECT s.snapshot_date, s.country, s.location_count
        FROM snapshots s
        JOIN chains c ON s.chain_id = c.id
        WHERE c.canonical_name = ?
        ORDER BY s.snapshot_date
    """, (chain_name,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@st.cache_data(ttl=300)
def load_chain_locations(chain_name: str):
    conn = get_connection()
    rows = conn.execute("""
        SELECT l.name, l.city, l.country, l.lat, l.lon, l.address_full, l.website
        FROM locations l
        JOIN chains c ON l.chain_id = c.id
        WHERE c.canonical_name = ? AND l.active = 1
    """, (chain_name,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@st.cache_data(ttl=300)
def load_analyses():
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, analysis_date, analysis_text, model_used
        FROM quarterly_analyses
        ORDER BY analysis_date DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@st.cache_data(ttl=300)
def load_unknown_chains():
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, canonical_name, location_count, competitive_classification,
               price_tier, normalized_18mo_cost, membership_model
        FROM chains
        WHERE competitive_classification = 'unknown' AND manually_reviewed = 0
        ORDER BY location_count DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_total_locations():
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) as cnt FROM locations WHERE active = 1").fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_last_refresh():
    conn = get_connection()
    row = conn.execute("SELECT MAX(last_seen_date) as d FROM locations").fetchone()
    conn.close()
    return row["d"] if row else "Never"


# ---------------------------------------------------------------------------
# Page: Setup (API key configuration)
# ---------------------------------------------------------------------------
if page == "Setup":
    st.title("Setup")
    st.markdown(
        "Configure secrets and API keys for Gym Intelligence. "
        "These are stored on the server in `/opt/gym-intelligence/.env` and are "
        "**never** sent back to the browser."
    )

    current_key = _get_api_key()
    key_status = "Set" if current_key else "Not set"
    key_masked = f"{current_key[:8]}...{current_key[-4:]}" if len(current_key) > 12 else ("(empty)" if not current_key else "***")

    st.subheader("Anthropic API Key")
    st.metric("Status", key_status)
    st.text(f"Current: {key_masked}")

    with st.form("api_key_form"):
        new_key = st.text_input(
            "ANTHROPIC_API_KEY",
            type="password",
            placeholder="sk-ant-api03-...",
            help="Enter your Anthropic API key. Required for AI classification and quarterly analysis.",
        )
        submitted = st.form_submit_button("Save API Key", use_container_width=True, type="primary")

        if submitted:
            if new_key and new_key.strip():
                _save_env_key("ANTHROPIC_API_KEY", new_key.strip())
                st.success("API key saved successfully. AI features are now enabled.")
                st.rerun()
            else:
                st.error("Please enter a valid API key.")

    st.divider()
    st.subheader("Server Info")
    st.text(f"Python: {sys.version}")
    st.text(f"Working dir: {os.getcwd()}")
    st.text(f"Env file: {ENV_PATH}")
    st.text(f"Env file exists: {ENV_PATH.exists()}")


# ---------------------------------------------------------------------------
# Page 1: Market Overview
# ---------------------------------------------------------------------------
elif page == "Market Overview":
    st.title("Market Overview")

    dates = load_snapshot_dates()
    if not dates:
        st.warning("No data yet. Run a data refresh from the Admin page.")
        st.stop()

    countries = ["All Europe"] + [COUNTRY_NAMES.get(c, c) for c in sorted(COUNTRY_NAMES.keys())]
    country_codes_rev = {v: k for k, v in COUNTRY_NAMES.items()}

    col1, col2 = st.columns(2)
    with col1:
        selected_country = st.selectbox("Country", countries)
    with col2:
        period_label = st.radio(
            "Period", ["Current Quarter", "Prior Quarter"], horizontal=True
        )

    min_locs = st.slider("Minimum locations", 1, 50, 5)

    country_param = selected_country
    if selected_country != "All Europe":
        country_param = country_codes_rev.get(selected_country, selected_country)

    snapshot_idx = 0 if period_label == "Current Quarter" else min(1, len(dates) - 1)
    selected_date = dates[snapshot_idx]

    data = load_market_data(selected_date, country_param, min_locs)
    if not data:
        st.info("No direct competitor data for this selection.")
        st.stop()

    if pd is None:
        st.error("pandas/plotly not installed. Charts unavailable.")
        st.stop()

    # Group small chains as "Other"
    main_chains = [d for d in data if d["total_locations"] >= min_locs]
    other_count = sum(d["total_locations"] for d in data if d["total_locations"] < min_locs)
    total = sum(d["total_locations"] for d in data)

    chart_data = [{"Chain": d["canonical_name"], "Locations": d["total_locations"]} for d in main_chains]
    if other_count > 0:
        chart_data.append({"Chain": "Other", "Locations": other_count})

    df = pd.DataFrame(chart_data)
    fig = px.bar(
        df, x="Chain", y="Locations",
        title=f"Market Share by Location Count — {selected_country} ({selected_date})",
        color="Chain",
    )
    fig.update_layout(
        height=400, showlegend=False,
        xaxis_tickangle=-45, margin=dict(b=120),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Chain detail cards
    st.subheader("Chain Details")

    # Try to get QoQ data if prior quarter exists
    qoq_map = {}
    if len(dates) >= 2:
        qoq_data = load_qoq_data(dates[0], dates[1], country_param)
        for q in qoq_data:
            prev = q["previous_count"]
            curr = q["current_count"]
            change_pct = ((curr - prev) / prev * 100) if prev > 0 else None
            qoq_map[q["canonical_name"]] = {
                "current": curr, "previous": prev, "change_pct": change_pct
            }

    for chain in main_chains:
        name = chain["canonical_name"]
        locs = chain["total_locations"]
        share = locs / total * 100 if total > 0 else 0
        tier = chain["price_tier"] or "unknown"
        cost = chain["normalized_18mo_cost"]
        qoq = qoq_map.get(name, {})
        change = qoq.get("change_pct")

        with st.expander(f"**{name}** — {locs} locations ({share:.1f}%)"):
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Locations", locs, delta=f"{change:+.1f}%" if change is not None else None)
                st.metric("Price Tier", tier.replace("_", " ").title())
            with c2:
                st.metric("18-mo Cost", f"€{cost:.0f}" if cost else "N/A")
                st.metric("Market Share", f"{share:.1f}%")


# ---------------------------------------------------------------------------
# Page 2: Chain Explorer
# ---------------------------------------------------------------------------
elif page == "Chain Explorer":
    st.title("Chain Explorer")

    min_locs = st.slider("Minimum locations", 1, 50, 3, key="explorer_min")
    chains = load_chains_list(min_locs)

    if not chains:
        st.warning("No chains found. Run a data refresh first.")
        st.stop()

    chain_names = [c["canonical_name"] for c in chains]
    selected_chain = st.selectbox("Select Chain", chain_names)

    detail = load_chain_detail(selected_chain)
    if not detail:
        st.error("Chain not found.")
        st.stop()

    if pd is None:
        st.error("pandas/plotly not installed. Charts unavailable.")
        st.stop()

    # Profile card
    st.subheader("Chain Profile")
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Classification", (detail["competitive_classification"] or "unknown").replace("_", " ").title())
        st.metric("Price Tier", (detail["price_tier"] or "unknown").replace("_", " ").title())
        st.metric("Total Locations", detail["location_count"])
    with c2:
        st.metric("18-mo Cost", f"€{detail['normalized_18mo_cost']:.0f}" if detail["normalized_18mo_cost"] else "N/A")
        st.metric("Membership Model", (detail["membership_model"] or "unknown").replace("_", " ").title())
        st.metric("Manually Reviewed", "Yes" if detail["manually_reviewed"] else "No")

    if detail["ai_classification_rationale"]:
        st.info(f"**Rationale:** {detail['ai_classification_rationale']}")

    # Snapshot history chart
    snap_data = load_chain_snapshots(selected_chain)
    if snap_data:
        st.subheader("Location Count Over Time")
        df_snap = pd.DataFrame(snap_data)
        df_snap["country_name"] = df_snap["country"].map(COUNTRY_NAMES)
        fig = px.line(
            df_snap, x="snapshot_date", y="location_count", color="country_name",
            title=f"{selected_chain} — Locations Over Time",
            labels={"snapshot_date": "Date", "location_count": "Locations", "country_name": "Country"},
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

    # QoQ growth by country
    dates = load_snapshot_dates()
    if len(dates) >= 2:
        st.subheader("QoQ Growth by Country")
        conn = get_connection()
        growth_rows = conn.execute("""
            SELECT
                s1.country,
                SUM(s1.location_count) as curr,
                COALESCE(SUM(s2.location_count), 0) as prev
            FROM snapshots s1
            JOIN chains c ON s1.chain_id = c.id
            LEFT JOIN snapshots s2
                ON s2.chain_id = s1.chain_id AND s2.country = s1.country
                AND s2.snapshot_date = ?
            WHERE s1.snapshot_date = ? AND c.canonical_name = ?
            GROUP BY s1.country
        """, (dates[1], dates[0], selected_chain)).fetchall()
        conn.close()

        cols = st.columns(min(len(growth_rows), 3)) if growth_rows else []
        for i, row in enumerate(growth_rows):
            with cols[i % len(cols)]:
                curr, prev = row["curr"], row["prev"]
                delta = ((curr - prev) / prev * 100) if prev > 0 else None
                st.metric(
                    COUNTRY_NAMES.get(row["country"], row["country"]),
                    curr,
                    delta=f"{delta:+.1f}%" if delta is not None else "New",
                )

    # Map
    locs = load_chain_locations(selected_chain)
    if locs:
        st.subheader("Active Locations")
        df_locs = pd.DataFrame(locs)
        df_locs = df_locs.dropna(subset=["lat", "lon"])

        if not df_locs.empty:
            fig = px.scatter_mapbox(
                df_locs,
                lat="lat", lon="lon",
                hover_name="name",
                hover_data=["city", "country", "address_full"],
                zoom=4,
                color_discrete_sequence=["#FF6B35"],
            )
            fig.update_layout(
                mapbox_style="open-street-map",
                height=400,
                margin=dict(l=0, r=0, t=0, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Page 3: Competitive Analysis
# ---------------------------------------------------------------------------
elif page == "Competitive Analysis":
    st.title("Competitive Analysis")

    analyses = load_analyses()
    if not analyses:
        st.warning("No analyses yet. Run the full pipeline from the Admin page.")
        st.stop()

    analysis_options = {f"{a['analysis_date']} (#{a['id']})": a for a in analyses}
    selected_key = st.selectbox("Select Quarter", list(analysis_options.keys()))
    selected = analysis_options[selected_key]

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Date", selected["analysis_date"])
    with c2:
        st.metric("Model", selected["model_used"])
    with c3:
        st.metric("Locations in DB", get_total_locations())

    st.divider()
    st.markdown(selected["analysis_text"])


# ---------------------------------------------------------------------------
# Page 4: Admin / Refresh
# ---------------------------------------------------------------------------
elif page == "Admin / Refresh":
    st.title("Admin / Refresh")

    st.metric("Last Refresh", get_last_refresh())
    st.metric("Active Locations", get_total_locations())

    # Run pipeline
    st.subheader("Run Data Refresh")
    if st.button("Run Data Refresh Now", use_container_width=True, type="primary"):
        log_output = st.empty()
        progress_text = []

        def run_step(label, module_name, func_name):
            progress_text.append(f"**{label}** — running...")
            log_output.markdown("\n\n".join(progress_text))
            try:
                mod = __import__(module_name)
                getattr(mod, func_name)()
                progress_text[-1] = f"**{label}** — done ✓"
            except Exception as e:
                progress_text[-1] = f"**{label}** — FAILED: {e}"
            log_output.markdown("\n\n".join(progress_text))

        run_step("Step 1/3: Data Collection", "collect", "run_collection")
        run_step("Step 2/3: Chain Classification", "classify", "run_classification")
        run_step("Step 3/3: Quarterly Analysis", "analyze", "run_analysis")

        st.success("Pipeline complete!")
        st.cache_data.clear()

    # Manual review section
    st.subheader("Chains Pending Review")
    unknown_chains = load_unknown_chains()

    if not unknown_chains:
        st.info("No chains pending review.")
    else:
        for chain in unknown_chains[:20]:
            with st.expander(f"**{chain['canonical_name']}** ({chain['location_count']} locations)"):
                with st.form(key=f"review_{chain['id']}"):
                    new_class = st.selectbox(
                        "Classification",
                        ["unknown", "direct_competitor", "non_competitor"],
                        key=f"class_{chain['id']}",
                    )
                    new_tier = st.selectbox(
                        "Price Tier",
                        ["unknown", "budget", "mid_market", "premium"],
                        key=f"tier_{chain['id']}",
                    )
                    new_cost = st.number_input(
                        "18-month Cost (€)", value=0.0, min_value=0.0, step=10.0,
                        key=f"cost_{chain['id']}",
                    )
                    new_model = st.selectbox(
                        "Membership Model",
                        ["unknown", "commitment", "flexible", "mixed"],
                        key=f"model_{chain['id']}",
                    )

                    if st.form_submit_button("Save Review", use_container_width=True):
                        conn = get_connection()
                        conn.execute("""
                            UPDATE chains SET
                                competitive_classification = ?,
                                price_tier = ?,
                                normalized_18mo_cost = ?,
                                membership_model = ?,
                                manually_reviewed = 1
                            WHERE id = ?
                        """, (
                            new_class, new_tier,
                            new_cost if new_cost > 0 else None,
                            new_model, chain["id"],
                        ))
                        conn.commit()
                        conn.close()
                        st.success(f"Updated {chain['canonical_name']}")
                        st.cache_data.clear()

    # CSV export
    st.subheader("Export Data")
    if st.button("Export Database to CSV", use_container_width=True):
        conn = get_connection()
        tables = ["locations", "chains", "snapshots", "quarterly_analyses"]
        zip_buffer = io.BytesIO()

        import zipfile
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for table in tables:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                if rows:
                    output = io.StringIO()
                    writer = csv.writer(output)
                    writer.writerow(rows[0].keys())
                    for row in rows:
                        writer.writerow(tuple(row))
                    zf.writestr(f"{table}.csv", output.getvalue())

        conn.close()
        st.download_button(
            "Download ZIP",
            data=zip_buffer.getvalue(),
            file_name=f"gym_intelligence_export_{date.today().isoformat()}.zip",
            mime="application/zip",
            use_container_width=True,
        )
