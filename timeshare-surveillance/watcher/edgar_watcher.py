#!/usr/bin/env python3
"""Long-running EDGAR Atom feed watcher.

Polls EDGAR per ticker (10-K + 10-Q feeds) every POLL_INTERVAL_SEC,
staggered STAGGER_SEC between tickers. When a new accession is seen,
kicks off fetch_and_parse → merge → red_flag_diff; if the diff reports
changes, pipes the diff JSON to email_alert.py.

Subprocesses use the interpreter from $PYTHON_EXE (set by the systemd unit),
falling back to sys.executable.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import settings  # noqa: E402

POLL_INTERVAL_SEC = 15 * 60  # 15 minutes
STAGGER_SEC = 5              # between tickers

log = logging.getLogger("edgar_watcher")


def _setup_logging() -> None:
    try:
        settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
        handlers = [
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(settings.LOG_DIR / "watcher.log"),
        ]
    except PermissionError:
        handlers = [logging.StreamHandler(sys.stdout)]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def _python_exe() -> str:
    return os.environ.get("PYTHON_EXE") or sys.executable


def _load_seen() -> dict:
    try:
        with open(settings.SEEN_ACCESSIONS_JSON) as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_seen(seen: dict) -> None:
    settings.SEEN_ACCESSIONS_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings.SEEN_ACCESSIONS_JSON.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(seen, f, indent=2, default=str)
    os.replace(tmp, settings.SEEN_ACCESSIONS_JSON)


def _fetch_atom(url: str) -> str:
    import requests

    r = requests.get(
        url,
        headers={"User-Agent": settings.EDGAR_USER_AGENT, "Accept": "application/atom+xml"},
        timeout=30,
    )
    r.raise_for_status()
    return r.text


def _parse_accessions(atom_xml: str) -> list[str]:
    """Return accession numbers referenced in an EDGAR Atom feed."""
    try:
        root = ET.fromstring(atom_xml)
    except ET.ParseError as e:
        log.warning("could not parse atom feed: %s", e)
        return []
    accs: list[str] = []
    # Atom namespace varies; strip with localname match.
    for elem in root.iter():
        tag = elem.tag.split("}", 1)[-1].lower()
        if tag in ("id", "title", "link"):
            text = (elem.text or "") + " " + (elem.attrib.get("href") or "")
            # accession pattern: 10 digits - 2 digits - 6 digits
            import re

            for m in re.finditer(r"\d{10}-\d{2}-\d{6}", text):
                accs.append(m.group(0))
    # de-dupe preserve order
    seen = set()
    uniq = []
    for a in accs:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq


def _poll_ticker(ticker: str, cik: str, seen: dict) -> list[str]:
    new_accs: list[str] = []
    ticker_seen = set(seen.get(ticker, []))
    for ftype in settings.FILING_TYPES:
        url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&CIK={cik}&type={ftype}&dateb=&owner=include&count=5&output=atom"
        )
        try:
            xml = _fetch_atom(url)
        except Exception as e:
            log.warning("atom fetch failed for %s %s: %s", ticker, ftype, e)
            continue
        for acc in _parse_accessions(xml):
            if acc not in ticker_seen:
                ticker_seen.add(acc)
                new_accs.append(acc)
                log.info("NEW filing detected: %s %s %s", ticker, ftype, acc)
    seen[ticker] = sorted(ticker_seen)
    return new_accs


def _run(cmd: list[str], stdin_bytes: bytes | None = None, capture_stdout: bool = False) -> subprocess.CompletedProcess:
    log.info("subprocess: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(settings.BASE_DIR),
        input=stdin_bytes,
        stdout=subprocess.PIPE if capture_stdout else None,
        check=False,
    )


def _process_ticker_update(ticker: str) -> None:
    py = _python_exe()
    fetch_cmd = [py, "pipeline/fetch_and_parse.py", "--ticker", ticker]
    res = _run(fetch_cmd)
    if res.returncode != 0:
        log.error("fetch_and_parse failed for %s (rc=%s)", ticker, res.returncode)
        return

    merge_cmd = [py, "pipeline/merge.py"]
    res = _run(merge_cmd)
    if res.returncode != 0:
        log.error("merge failed (rc=%s)", res.returncode)
        return

    diff_cmd = [py, "pipeline/red_flag_diff.py"]
    res = _run(diff_cmd, capture_stdout=True)
    if res.returncode == 1 and res.stdout:
        # changes detected — pipe to email_alert
        log.info("red_flag_diff reports changes; sending email alert")
        email_res = _run([py, "alerts/email_alert.py"], stdin_bytes=res.stdout)
        if email_res.returncode != 0:
            log.warning("email_alert returned rc=%s", email_res.returncode)
    elif res.returncode == 0:
        log.info("red_flag_diff: no changes for %s", ticker)
    else:
        log.error("red_flag_diff unexpected rc=%s", res.returncode)


_SHUTDOWN = False


def _handle_signal(signum, frame):
    global _SHUTDOWN
    log.info("signal %s received, shutting down after this cycle", signum)
    _SHUTDOWN = True


def main() -> int:
    _setup_logging()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log.info("edgar_watcher starting; interval=%ss stagger=%ss tickers=%s",
             POLL_INTERVAL_SEC, STAGGER_SEC, [t["ticker"] for t in settings.TARGETS])

    while not _SHUTDOWN:
        seen = _load_seen()
        first_cycle = not seen  # treat initial population as seed, no alerts
        for idx, target in enumerate(settings.TARGETS):
            if _SHUTDOWN:
                break
            if idx > 0:
                time.sleep(STAGGER_SEC)
            ticker = target["ticker"]
            cik = target["cik"]
            try:
                new_accs = _poll_ticker(ticker, cik, seen)
            except Exception as e:
                log.exception("polling %s failed: %s", ticker, e)
                continue
            if new_accs and not first_cycle:
                try:
                    _process_ticker_update(ticker)
                except Exception as e:
                    log.exception("processing update for %s failed: %s", ticker, e)
            elif new_accs and first_cycle:
                log.info("seeding seen_accessions for %s (%d filings), no alert",
                         ticker, len(new_accs))
            _save_seen(seen)

        if _SHUTDOWN:
            break
        log.info("sleeping %ss until next cycle", POLL_INTERVAL_SEC)
        for _ in range(POLL_INTERVAL_SEC):
            if _SHUTDOWN:
                break
            time.sleep(1)

    log.info("edgar_watcher stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
