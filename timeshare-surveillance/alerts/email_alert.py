#!/usr/bin/env python3
"""Render and send a surveillance email alert.

Input: JSON diff summary on stdin (from red_flag_diff.py).
Behavior:
    - If --weekly, or stdin summary has weekly:true, render the weekly template.
    - Otherwise render the event-driven template.
    - Exit 0 on send. Exit 2 if SMTP config is missing.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import settings  # noqa: E402

log = logging.getLogger("email_alert")


SEVERITY_COLOR = {
    "CRITICAL": "#FF3B3B",
    "WARNING": "#FFB800",
    "RESOLVED": "#00D48A",
}


def _fmt_value(metric: str, val) -> str:
    if val is None:
        return "n/a"
    if isinstance(val, bool):
        return "true" if val else "false"
    if metric.endswith("_pct") or metric.endswith("_rate_pct"):
        try:
            return f"{float(val) * 100:.2f}%"
        except (TypeError, ValueError):
            return str(val)
    if metric.endswith("_mm"):
        try:
            return f"${float(val):,.1f}M"
        except (TypeError, ValueError):
            return str(val)
    if metric.endswith("_dollars"):
        try:
            return f"${float(val):,.0f}"
        except (TypeError, ValueError):
            return str(val)
    return str(val)


def _row(color: str, ticker: str, metric: str, body: str) -> str:
    return (
        f'<tr style="border-left:4px solid {color};">'
        f'<td style="padding:8px 12px;font-weight:600;white-space:nowrap;">{html.escape(ticker)}</td>'
        f'<td style="padding:8px 12px;font-family:ui-monospace,Menlo,monospace;">{html.escape(metric)}</td>'
        f'<td style="padding:8px 12px;">{body}</td>'
        f'</tr>'
    )


def _section(title: str, color: str, rows: list[str]) -> str:
    if not rows:
        return ""
    return (
        f'<h2 style="color:{color};font-size:16px;margin:20px 0 6px 0;">{html.escape(title)}</h2>'
        f'<table style="border-collapse:collapse;width:100%;background:#fafafa;">'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def render_html(summary: dict) -> tuple[str, str]:
    weekly = bool(summary.get("weekly"))
    tickers = ", ".join(summary.get("tickers") or [])
    total_new = len(summary.get("new") or [])
    total_esc = len(summary.get("escalated") or [])
    total_res = len(summary.get("resolved") or [])
    total_active = len(summary.get("active") or [])

    if weekly:
        subject = f"[Timeshare Surveillance] Weekly digest — {total_active} active flags ({tickers})"
    else:
        parts = []
        if total_new:
            parts.append(f"{total_new} NEW")
        if total_esc:
            parts.append(f"{total_esc} ESCALATED")
        if total_res:
            parts.append(f"{total_res} RESOLVED")
        headline = ", ".join(parts) or "update"
        subject = f"[Timeshare Surveillance] {headline} — {tickers}"

    new_rows = [
        _row(
            SEVERITY_COLOR.get(f.get("severity"), "#888"),
            f["ticker"], f["metric"],
            f'<b style="color:{SEVERITY_COLOR.get(f.get("severity"), "#888")}">'
            f'{html.escape(str(f.get("severity", "")))}</b> — '
            f'value {_fmt_value(f["metric"], f.get("value"))} '
            f'(threshold {f.get("op","")} {_fmt_value(f["metric"], f.get("threshold"))})'
        )
        for f in (summary.get("new") or [])
    ]
    esc_rows = [
        _row(
            SEVERITY_COLOR["CRITICAL"], f["ticker"], f["metric"],
            f'{html.escape(str(f.get("from_severity","")))} → '
            f'<b style="color:{SEVERITY_COLOR["CRITICAL"]}">'
            f'{html.escape(str(f.get("to_severity","")))}</b> '
            f'— value {_fmt_value(f["metric"], f.get("value"))}'
        )
        for f in (summary.get("escalated") or [])
    ]
    res_rows = [
        _row(
            SEVERITY_COLOR["RESOLVED"], f["ticker"], f["metric"],
            f'No longer tripping threshold '
            f'(was {html.escape(str(f.get("previous_severity","")))}, '
            f'{_fmt_value(f["metric"], f.get("previous_value"))})'
        )
        for f in (summary.get("resolved") or [])
    ]
    active_rows = [
        _row(
            SEVERITY_COLOR.get(f.get("severity"), "#888"),
            f["ticker"], f["metric"],
            f'<b style="color:{SEVERITY_COLOR.get(f.get("severity"), "#888")}">'
            f'{html.escape(str(f.get("severity", "")))}</b> — '
            f'value {_fmt_value(f["metric"], f.get("value"))}'
        )
        for f in (summary.get("active") or [])
    ]

    generated = summary.get("generated_at") or datetime.now(timezone.utc).isoformat()

    body = f"""<!doctype html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;max-width:720px;margin:0 auto;padding:18px;color:#222;">
<div style="background:#111;color:#fff;padding:14px 18px;border-radius:6px;">
  <div style="font-size:18px;font-weight:700;">Timeshare Receivable Surveillance</div>
  <div style="font-size:13px;opacity:0.85;margin-top:2px;">Coverage: HGV · VAC · TNL · Generated {html.escape(generated)}</div>
</div>
{_section("NEW FLAGS", SEVERITY_COLOR["CRITICAL"], new_rows)}
{_section("ESCALATED", SEVERITY_COLOR["CRITICAL"], esc_rows)}
{_section("RESOLVED", SEVERITY_COLOR["RESOLVED"], res_rows)}
{_section("ACTIVE FLAGS", SEVERITY_COLOR["WARNING"], active_rows) if weekly or active_rows else ""}
<p style="color:#666;font-size:12px;margin-top:24px;line-height:1.5;">
View full dashboard: {html.escape(settings.DASHBOARD_URL)}<br>
Source: SEC EDGAR filings. Not investment advice. Automated extraction may contain errors — verify against primary filings before acting.
</p>
</body></html>"""

    return subject, body


def send(subject: str, html_body: str) -> int:
    host = settings.SMTP_HOST
    user = settings.SMTP_USER
    password = settings.SMTP_PASSWORD
    to_addr = settings.ALERT_EMAIL
    if not (host and user and password and to_addr):
        log.error("SMTP env vars missing (SMTP_HOST/SMTP_USER/SMTP_PASSWORD/ALERT_EMAIL); cannot send.")
        return 2
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(host, settings.SMTP_PORT, timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(user, password)
            s.sendmail(user, [to_addr], msg.as_string())
        log.info("sent alert: %s", subject)
        return 0
    except Exception as e:
        log.exception("SMTP send failed: %s", e)
        return 2


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly", action="store_true", help="Render weekly digest template")
    args = ap.parse_args()

    raw = sys.stdin.read().strip()
    if not raw:
        log.error("no input on stdin")
        return 2
    try:
        summary = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("input not valid JSON: %s", e)
        return 2

    if args.weekly:
        summary["weekly"] = True

    subject, body = render_html(summary)
    return send(subject, body)


if __name__ == "__main__":
    sys.exit(main())
