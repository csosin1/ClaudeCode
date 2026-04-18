#!/bin/bash
# accept-card.sh — emit a persistent structured Accept card.
#
# A card is:
#   (a) an HTML page written to /var/www/landing/accept-cards/<id>.html (persistent;
#       survives dormancy so a returning user can still see/act on it days later),
#   (b) a JSON sidecar at /var/www/landing/accept-cards/<id>.json (for programmatic
#       reading by dashboards / future automation),
#   (c) a milestone-tier ntfy notification pointing at the HTML URL.
#
# Fields (all flags, all optional except title + outcome):
#   --title                 short, ≤60 chars
#   --outcome               one sentence: what happened / what needs decision
#   --preview-url           URL to preview build, diff, or artefact
#   --outside-spend         estimated outside spend in USD (number; omit if 0 — NOT a token cost)
#   --actions               CSV of action labels (default: "Accept,Retry,Cancel")
#   --context-link          URL to full commit / CHANGES entry / log
#   --tier                  ntfy tier override (default: milestone; critical for HITL blockers)
#   --id                    override auto-generated card id (useful for updates)
#
# Stdout: the public URL of the rendered card.
# See SKILLS/walkaway-invariants.md (invariant #3) and SKILLS/dual-surface-parity.md.

set -euo pipefail

CARDS_DIR="/var/www/landing/accept-cards"
BASE_URL="https://casinv.dev/accept-cards"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

TITLE=""
OUTCOME=""
PREVIEW_URL=""
OUTSIDE_SPEND=""
ACTIONS="Accept,Retry,Cancel"
CONTEXT_LINK=""
TIER="milestone"
CARD_ID=""

while [ $# -gt 0 ]; do
    case "$1" in
        --title)          TITLE="$2"; shift 2 ;;
        --outcome)        OUTCOME="$2"; shift 2 ;;
        --preview-url)    PREVIEW_URL="$2"; shift 2 ;;
        --outside-spend)  OUTSIDE_SPEND="$2"; shift 2 ;;
        --actions)        ACTIONS="$2"; shift 2 ;;
        --context-link)   CONTEXT_LINK="$2"; shift 2 ;;
        --tier)           TIER="$2"; shift 2 ;;
        --id)             CARD_ID="$2"; shift 2 ;;
        *) echo "accept-card.sh: unknown arg '$1'" >&2; exit 2 ;;
    esac
done

[ -n "$TITLE" ]   || { echo "accept-card.sh: --title required" >&2; exit 2; }
[ -n "$OUTCOME" ] || { echo "accept-card.sh: --outcome required" >&2; exit 2; }

mkdir -p "$CARDS_DIR"

if [ -z "$CARD_ID" ]; then
    CARD_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(tr -dc 'a-z0-9' </dev/urandom | head -c6)"
fi

TS_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
HTML_PATH="$CARDS_DIR/$CARD_ID.html"
JSON_PATH="$CARDS_DIR/$CARD_ID.json"
PUBLIC_URL="$BASE_URL/$CARD_ID.html"

# --- Render via python for safe HTML/JSON escaping ---------------------------
# Use a quoted heredoc ('PY') so bash does NOT expand vars inside; pass values via env.
export CARD_ID TITLE OUTCOME PREVIEW_URL OUTSIDE_SPEND ACTIONS CONTEXT_LINK TIER TS_ISO HTML_PATH JSON_PATH
python3 - <<'PY'
import html, json, os

card_id = os.environ["CARD_ID"]
title = os.environ["TITLE"]
outcome = os.environ["OUTCOME"]
preview_url = os.environ.get("PREVIEW_URL", "")
outside_spend = os.environ.get("OUTSIDE_SPEND", "")
actions = [a.strip() for a in os.environ.get("ACTIONS", "").split(",") if a.strip()]
context_link = os.environ.get("CONTEXT_LINK", "")
tier = os.environ.get("TIER", "milestone")
ts_iso = os.environ["TS_ISO"]
html_path = os.environ["HTML_PATH"]
json_path = os.environ["JSON_PATH"]

# JSON sidecar — omit outside_spend when empty / zero (NOT a token cost surface)
payload = {
    "id": card_id,
    "ts": ts_iso,
    "title": title,
    "outcome": outcome,
    "tier": tier,
    "actions": actions,
}
if preview_url:
    payload["preview_url"] = preview_url
if context_link:
    payload["context_link"] = context_link
if outside_spend and outside_spend not in ("0", "0.00", "0.0"):
    try:
        payload["outside_spend_estimated_usd"] = float(outside_spend)
    except ValueError:
        payload["outside_spend_estimated_usd"] = outside_spend

with open(json_path, "w") as f:
    json.dump(payload, f, indent=2)

# HTML page: mobile-first AND desktop (see SKILLS/dual-surface-parity.md).
# - 390px: buttons in bottom third, ≥44px tap targets, plain URLs.
# - 1280px: keyboard-navigable, max-width 720px, Enter=Accept, Esc=Cancel.
def esc(s): return html.escape(s or "")

spend_block = ""
if "outside_spend_estimated_usd" in payload:
    amount = payload["outside_spend_estimated_usd"]
    spend_block = (
        '<div class="field"><span class="lbl">Outside spend (est.)</span>'
        f'<span class="val">${amount}</span></div>'
    )

preview_block = ""
if preview_url:
    preview_block = (
        f'<div class="field"><span class="lbl">Preview</span>'
        f'<a class="val link" href="{esc(preview_url)}">{esc(preview_url)}</a></div>'
    )

context_block = ""
if context_link:
    context_block = (
        f'<div class="field"><span class="lbl">Context</span>'
        f'<a class="val link" href="{esc(context_link)}">{esc(context_link)}</a></div>'
    )

# Build action buttons. First action is the primary (highlighted + Enter binding).
btn_html = []
for i, a in enumerate(actions):
    cls = "btn btn-primary" if i == 0 else ("btn btn-cancel" if a.lower() == "cancel" else "btn")
    btn_html.append(f'<button class="{cls}" data-action="{esc(a)}" tabindex="{i+1}">{esc(a)}</button>')

buttons = "\n      ".join(btn_html)

page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Accept card</title>
<style>
  :root {{ --fg:#111; --mut:#555; --bg:#fafafa; --card:#fff; --accent:#0b5fff; --cancel:#a33; --border:#e3e3e3; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin:0; padding:0; background:var(--bg); color:var(--fg);
               font: 16px/1.45 -apple-system, system-ui, Segoe UI, Roboto, sans-serif; }}
  main {{ max-width: 720px; margin: 0 auto; padding: 20px 16px 120px; }}
  h1 {{ font-size: 22px; margin: 4px 0 6px; line-height:1.25; }}
  .meta {{ color: var(--mut); font-size: 13px; margin-bottom: 14px; }}
  .card {{ background: var(--card); border:1px solid var(--border); border-radius: 12px;
           padding: 18px; }}
  .outcome {{ font-size: 17px; margin: 0 0 16px; }}
  .field {{ display:flex; flex-direction:column; padding: 10px 0; border-top: 1px solid var(--border); }}
  .field .lbl {{ font-size: 12px; color: var(--mut); text-transform: uppercase; letter-spacing: 0.04em; }}
  .field .val {{ font-size: 15px; word-break: break-all; }}
  .field .link {{ color: var(--accent); text-decoration: none; }}
  .field .link:hover {{ text-decoration: underline; }}
  .actions {{ position: fixed; left: 0; right: 0; bottom: 0; background: var(--card);
              border-top: 1px solid var(--border); padding: 12px 16px;
              display:flex; gap: 10px; justify-content: flex-end; flex-wrap: wrap; }}
  .btn {{ min-height: 48px; min-width: 96px; padding: 0 18px; font-size: 16px;
          border-radius: 10px; border: 1px solid var(--border); background: #fff; color: var(--fg);
          cursor: pointer; }}
  .btn:focus {{ outline: 3px solid var(--accent); outline-offset: 2px; }}
  .btn-primary {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  .btn-cancel {{ color: var(--cancel); }}
  @media (min-width: 720px) {{
    main {{ padding: 28px 24px 28px; }}
    .actions {{ position: static; border: 0; padding: 16px 0 0; background: transparent;
                justify-content: flex-start; }}
  }}
</style>
</head>
<body>
<main>
  <div class="meta">Accept card · {esc(tier)} · {esc(ts_iso)} · id {esc(card_id)}</div>
  <h1>{esc(title)}</h1>
  <div class="card">
    <p class="outcome">{esc(outcome)}</p>
    {preview_block}
    {spend_block}
    {context_block}
    <div class="actions" role="group" aria-label="Actions">
      {buttons}
    </div>
  </div>
</main>
<script>
  // Keyboard nav (desktop parity): Enter triggers primary; Esc triggers Cancel if present.
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Enter') {{
      const primary = document.querySelector('.btn-primary');
      if (primary) primary.click();
    }} else if (e.key === 'Escape') {{
      const cancel = document.querySelector('.btn-cancel');
      if (cancel) cancel.click();
    }}
  }});
  // Button click = log an action-intent to the server (future: POST to /accept-cards/ack).
  // For now, click marks the button pressed visually and opens context_link if primary.
  document.querySelectorAll('.btn').forEach(function(b) {{
    b.addEventListener('click', function() {{
      b.setAttribute('aria-pressed','true');
      b.style.opacity = '0.6';
    }});
  }});
</script>
</body>
</html>
"""

with open(html_path, "w") as f:
    f.write(page)
PY

# --- Fire the notification via notify.sh at the requested tier ---------------
if [ -x /etc/ntfy-topic ] || [ -s /etc/ntfy-topic ]; then
    "$SCRIPT_DIR/notify.sh" "$OUTCOME" "$TITLE" --tier "$TIER" --click "$PUBLIC_URL" || true
fi

echo "$PUBLIC_URL"
