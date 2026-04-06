"""Flask web UI for gym intelligence tool.

Deployed behind nginx at /gym-intelligence/. All routes are mounted under
a Blueprint with url_prefix so they work both directly and behind the proxy.
"""

import csv
import io
import json
import os
import sys
import threading
import traceback
import zipfile
from datetime import date
from pathlib import Path

from flask import (
    Blueprint,
    Flask,
    jsonify,
    render_template,
    request,
    send_file,
)

from db import COUNTRY_NAMES, get_connection, init_db

# ---------------------------------------------------------------------------
# .env loading
# ---------------------------------------------------------------------------
ENV_PATH = Path("/opt/gym-intelligence/.env")
if not ENV_PATH.exists():
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
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(lines) + "\n")
    os.environ[key] = value


def _get_api_key() -> str:
    _load_env()
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


_load_env()
init_db()

# ---------------------------------------------------------------------------
# Background refresh state
# ---------------------------------------------------------------------------
_refresh_lock = threading.Lock()
_refresh_running = False
_refresh_log: list[str] = []


def _run_refresh():
    global _refresh_running

    def progress(msg):
        _refresh_log.append(msg)

    try:
        import collect
        import classify
        import analyze

        # Step 1: Collection (no API key needed)
        progress("=== Step 1/3: Data Collection ===")
        try:
            collect.run_collection(progress_cb=progress)
        except Exception as e:
            progress(f"Collection FAILED: {e}")

        # Step 2: Classification (needs API key)
        _load_env()
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            progress("=== Step 2/3: Classification — SKIPPED (no API key) ===")
            progress("=== Step 3/3: Analysis — SKIPPED (no API key) ===")
            progress("Done. Set your API key in Admin tab to enable classification & analysis.")
        else:
            progress("=== Step 2/3: Chain Classification ===")
            try:
                classify.run_classification(progress_cb=progress)
            except Exception as e:
                progress(f"Classification FAILED: {e}")

            progress("=== Step 3/3: Quarterly Analysis ===")
            try:
                analyze.run_analysis(progress_cb=progress)
            except Exception as e:
                progress(f"Analysis FAILED: {e}")

            progress("Pipeline complete.")
    except Exception as e:
        progress(f"Pipeline error: {e}")
    finally:
        with _refresh_lock:
            _refresh_running = False


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
bp = Blueprint("gym", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


# --- API endpoints --------------------------------------------------------

@bp.route("/api/snapshot-dates")
def api_snapshot_dates():
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT snapshot_date FROM snapshots ORDER BY snapshot_date DESC"
    ).fetchall()
    conn.close()
    return jsonify([r["snapshot_date"] for r in rows])


@bp.route("/api/market-data")
def api_market_data():
    snapshot_date = request.args.get("date", "")
    country = request.args.get("country", "All Europe")
    try:
        min_locations = int(request.args.get("min_locations", "5"))
    except (ValueError, TypeError):
        min_locations = 5

    conn = get_connection()
    params: list = [snapshot_date]
    country_filter = ""
    if country and country != "All Europe":
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
        HAVING total_locations >= ?
        ORDER BY total_locations DESC
    """, params + [min_locations]).fetchall()
    conn.close()

    total = sum(r["total_locations"] for r in rows)
    result = []
    for r in rows:
        d = dict(r)
        d["market_share"] = round(r["total_locations"] / total * 100, 1) if total > 0 else 0
        result.append(d)
    return jsonify(result)


@bp.route("/api/chains")
def api_chains():
    try:
        min_locations = int(request.args.get("min_locations", "1"))
    except (ValueError, TypeError):
        min_locations = 1
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, canonical_name, location_count, competitive_classification
        FROM chains
        WHERE location_count >= ?
        ORDER BY location_count DESC
    """, (min_locations,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.route("/api/chain/<name>")
def api_chain_detail(name):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM chains WHERE canonical_name = ?", (name,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(row))


@bp.route("/api/chain/<name>/snapshots")
def api_chain_snapshots(name):
    conn = get_connection()
    rows = conn.execute("""
        SELECT s.snapshot_date, s.country, s.location_count
        FROM snapshots s
        JOIN chains c ON s.chain_id = c.id
        WHERE c.canonical_name = ?
        ORDER BY s.snapshot_date
    """, (name,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.route("/api/chain/<name>/locations")
def api_chain_locations(name):
    conn = get_connection()
    rows = conn.execute("""
        SELECT l.name, l.city, l.country, l.lat, l.lon, l.address_full, l.website
        FROM locations l
        JOIN chains c ON l.chain_id = c.id
        WHERE c.canonical_name = ? AND l.active = 1
    """, (name,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.route("/api/analyses")
def api_analyses():
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, analysis_date, model_used
        FROM quarterly_analyses
        ORDER BY analysis_date DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.route("/api/analysis/<int:analysis_id>")
def api_analysis_detail(analysis_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM quarterly_analyses WHERE id = ?", (analysis_id,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(row))


@bp.route("/api/unknown-chains")
def api_unknown_chains():
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, canonical_name, location_count, competitive_classification,
               price_tier, normalized_18mo_cost, membership_model
        FROM chains
        WHERE competitive_classification = 'unknown' AND manually_reviewed = 0
        ORDER BY location_count DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@bp.route("/api/review-chain", methods=["POST"])
def api_review_chain():
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"error": "missing chain id"}), 400

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
        data.get("classification", "unknown"),
        data.get("price_tier", "unknown"),
        float(data["cost"]) if data.get("cost") and str(data["cost"]).replace(".", "", 1).isdigit() and float(data["cost"]) > 0 else None,
        data.get("membership_model", "unknown"),
        data["id"],
    ))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@bp.route("/api/save-key", methods=["POST"])
def api_save_key():
    data = request.get_json()
    key = (data or {}).get("key", "").strip()
    if not key:
        return jsonify({"error": "empty key"}), 400
    _save_env_key("ANTHROPIC_API_KEY", key)
    return jsonify({"ok": True})


@bp.route("/api/status")
def api_status():
    conn = get_connection()
    loc_row = conn.execute("SELECT COUNT(*) as cnt FROM locations WHERE active = 1").fetchone()
    date_row = conn.execute("SELECT MAX(last_seen_date) as d FROM locations").fetchone()
    conn.close()
    api_key = _get_api_key()
    return jsonify({
        "total_locations": loc_row["cnt"] if loc_row else 0,
        "last_refresh": date_row["d"] if date_row and date_row["d"] else "Never",
        "api_key_set": bool(api_key),
        "api_key_preview": f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else ("(empty)" if not api_key else "***"),
    })


@bp.route("/api/refresh", methods=["POST"])
def api_refresh():
    global _refresh_running, _refresh_log
    with _refresh_lock:
        if _refresh_running:
            return jsonify({"error": "already running"}), 409
        _refresh_running = True
        _refresh_log = []
    t = threading.Thread(target=_run_refresh, daemon=True)
    t.start()
    return jsonify({"ok": True})


@bp.route("/api/refresh-status")
def api_refresh_status():
    with _refresh_lock:
        running = _refresh_running
    return jsonify({"running": running, "log": list(_refresh_log)})


@bp.route("/api/export")
def api_export():
    conn = get_connection()
    tables = ["locations", "chains", "snapshots", "quarterly_analyses"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
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
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"gym_intelligence_export_{date.today().isoformat()}.zip",
    )


# ---------------------------------------------------------------------------
# Country names endpoint (for frontend dropdowns)
# ---------------------------------------------------------------------------
@bp.route("/api/countries")
def api_countries():
    return jsonify(COUNTRY_NAMES)


# ---------------------------------------------------------------------------
# Mount blueprint and run
# ---------------------------------------------------------------------------
app.register_blueprint(bp, url_prefix="/gym-intelligence")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8502, debug=False)
