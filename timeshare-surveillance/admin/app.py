#!/usr/bin/env python3
"""Flask admin setup page for the timeshare-surveillance project.

Routes (all mounted under /admin/; the nginx proxy strips nothing, so paths
sent to the app start with /admin/):

  GET  /admin/        — setup page (basic-auth)
  POST /admin/save    — accept form, write .env atomically
  GET  /admin/status  — JSON status (basic-auth)

Auth: HTTP Basic, username `admin`, password from ADMIN_TOKEN env. If
ADMIN_TOKEN is not set in the env, every endpoint returns 503 with a clear
message (avoids accidentally shipping an unauthenticated admin page).
"""

from __future__ import annotations

import base64
import hmac
import logging
import os
import re
import sys
from functools import wraps
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import settings  # noqa: E402
from flask import Flask, flash, get_flashed_messages, jsonify, redirect, render_template, request, url_for  # noqa: E402

LOG_DIR = Path("/var/log/timeshare-surveillance")
LOG_FILE = LOG_DIR / "admin.log"

# Secret keys the user may populate via this page.
MANAGED_KEYS = [
    "ANTHROPIC_API_KEY",
    "SMTP_HOST",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "ALERT_EMAIL",
]


def _setup_logging() -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE)]
    except PermissionError:
        handlers = [logging.StreamHandler(sys.stdout)]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def create_app() -> Flask:
    _setup_logging()
    app = Flask(
        __name__,
        template_folder=str(_HERE / "templates"),
        static_folder=str(_HERE / "static"),
    )
    # Secret key for flashes only; rotate on restart — not used for auth.
    app.secret_key = os.urandom(24)
    app.logger.info("admin app starting; ADMIN_PORT=%s", os.environ.get("ADMIN_PORT", "8510"))

    env_path = settings.BASE_DIR / ".env"

    # ---------------- helpers ----------------

    def _parse_env() -> dict:
        data: dict[str, str] = {}
        if not env_path.exists():
            return data
        try:
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
        except OSError as e:
            app.logger.warning("could not read %s: %s", env_path, e)
        return data

    def _write_env(env: dict[str, str]) -> None:
        lines = [f"{k}={v}" for k, v in env.items()]
        content = "\n".join(lines) + "\n"
        tmp = env_path.with_suffix(".tmp")
        tmp.write_text(content)
        os.chmod(tmp, 0o600)
        os.replace(tmp, env_path)
        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass

    def _missing_keys() -> list[str]:
        env = _parse_env()
        return [k for k in MANAGED_KEYS if not env.get(k)]

    def _configured() -> bool:
        return not _missing_keys()

    def _valid_basic_auth(header: str | None) -> bool:
        token = os.environ.get("ADMIN_TOKEN", "")
        if not token:
            return False
        if not header or not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8", errors="replace")
        except Exception:
            return False
        if ":" not in decoded:
            return False
        user, pw = decoded.split(":", 1)
        user_ok = hmac.compare_digest(user, "admin")
        pw_ok = hmac.compare_digest(pw, token)
        return user_ok and pw_ok

    def require_admin(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not os.environ.get("ADMIN_TOKEN"):
                app.logger.error("ADMIN_TOKEN not configured; rejecting request")
                return (
                    jsonify({"error": "ADMIN_TOKEN not configured; rerun deploy"}),
                    503,
                )
            if not _valid_basic_auth(request.headers.get("Authorization")):
                app.logger.info("auth rejected for %s %s", request.method, request.path)
                return (
                    "Authentication required",
                    401,
                    {"WWW-Authenticate": 'Basic realm="timeshare-admin"'},
                )
            return fn(*args, **kwargs)

        return wrapper

    # ---------------- routes ----------------

    @app.get("/admin/")
    @require_admin
    def home():
        env = _parse_env()
        set_keys = [k for k in MANAGED_KEYS if env.get(k)]
        missing_keys = [k for k in MANAGED_KEYS if not env.get(k)]
        status = {
            "set_keys": set_keys,
            "missing_keys": missing_keys,
            "configured": not missing_keys,
        }
        return render_template(
            "setup.html",
            status=status,
            instance_label=os.environ.get("INSTANCE_LABEL", "preview"),
            flashes=get_flashed_messages(with_categories=True),
            dashboard_url=settings.DASHBOARD_URL,
            managed_keys=MANAGED_KEYS,
        )

    @app.post("/admin/save")
    @require_admin
    def save():
        env = _parse_env()
        # Reject newline injection; any other printable value is accepted.
        bad = []
        submitted: dict[str, str] = {}
        for key in MANAGED_KEYS:
            val = (request.form.get(key) or "").strip()
            if val == "":
                continue  # leave existing untouched
            if "\n" in val or "\r" in val:
                bad.append(key)
                continue
            # Conservative allow-list: no NUL or control chars.
            if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", val):
                bad.append(key)
                continue
            submitted[key] = val

        if bad:
            app.logger.warning("rejected invalid characters in %s", ",".join(bad))
            flash(f"Rejected invalid characters in: {', '.join(bad)}", "error")
            return redirect(url_for("home"))

        # Preserve any keys already present (e.g. ADMIN_TOKEN) and update/append managed.
        env.update(submitted)
        _write_env(env)
        app.logger.info(
            "admin saved keys: %s",
            ",".join(sorted(submitted.keys())) or "(none)",
        )
        flash(
            f"Saved {len(submitted)} value(s). "
            "Restart the watcher for changes to take effect.",
            "ok",
        )
        return redirect(url_for("home"))

    @app.get("/admin/status")
    def status():
        if not os.environ.get("ADMIN_TOKEN"):
            return (
                jsonify({"error": "ADMIN_TOKEN not configured; rerun deploy"}),
                503,
            )
        if not _valid_basic_auth(request.headers.get("Authorization")):
            return (
                jsonify({"error": "auth required"}),
                401,
                {"WWW-Authenticate": 'Basic realm="timeshare-admin"'},
            )
        return jsonify({
            "configured": _configured(),
            "missing_keys": _missing_keys(),
            "managed_keys": MANAGED_KEYS,
        })

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": "not found"}), 404

    return app


def main() -> int:
    app = create_app()
    port = int(os.environ.get("ADMIN_PORT", "8510"))
    # Bind to 127.0.0.1 — nginx proxies from there; never expose directly.
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
