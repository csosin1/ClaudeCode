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
#   --kind                  "milestone" (default) or "draft-plan" (kickoff refinement)
#   --draft-state-dir       (draft-plan only) path to .kickoff-state dir for YAML reads
#   --round                 (draft-plan only) integer round number, for display
#
# Stdout: the public URL of the rendered card.
# See SKILLS/walkaway-invariants.md (invariant #3) and SKILLS/dual-surface-parity.md.
# For --kind draft-plan: SKILLS/project-kickoff.md and feedback_committee_collaborative.md.

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
KIND="milestone"
DRAFT_STATE_DIR=""
ROUND=""

while [ $# -gt 0 ]; do
    case "$1" in
        --title)            TITLE="$2"; shift 2 ;;
        --outcome)          OUTCOME="$2"; shift 2 ;;
        --preview-url)      PREVIEW_URL="$2"; shift 2 ;;
        --outside-spend)    OUTSIDE_SPEND="$2"; shift 2 ;;
        --actions)          ACTIONS="$2"; shift 2 ;;
        --context-link)     CONTEXT_LINK="$2"; shift 2 ;;
        --tier)             TIER="$2"; shift 2 ;;
        --id)               CARD_ID="$2"; shift 2 ;;
        --kind)             KIND="$2"; shift 2 ;;
        --draft-state-dir)  DRAFT_STATE_DIR="$2"; shift 2 ;;
        --round)            ROUND="$2"; shift 2 ;;
        *) echo "accept-card.sh: unknown arg '$1'" >&2; exit 2 ;;
    esac
done

case "$KIND" in
    milestone|draft-plan) ;;
    *) echo "accept-card.sh: --kind must be 'milestone' or 'draft-plan' (got '$KIND')" >&2; exit 2 ;;
esac

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

# --- Draft Plan kind: kickoff refinement loop -------------------------------
# Separate renderer; reads YAML from DRAFT_STATE_DIR and surfaces disagreements +
# open questions as first-class card elements with action buttons.
if [ "$KIND" = "draft-plan" ]; then
    [ -n "$DRAFT_STATE_DIR" ] || { echo "accept-card.sh: --draft-state-dir required when --kind=draft-plan" >&2; exit 2; }
    [ -n "$ROUND" ] || ROUND="?"
    export CARD_ID TITLE OUTCOME CONTEXT_LINK TIER TS_ISO HTML_PATH JSON_PATH DRAFT_STATE_DIR ROUND ACTIONS OUTSIDE_SPEND
    python3 - <<'PY'
import html, json, os, pathlib, re

card_id = os.environ["CARD_ID"]
title   = os.environ["TITLE"]
outcome = os.environ["OUTCOME"]
ctx     = os.environ.get("CONTEXT_LINK", "")
tier    = os.environ.get("TIER", "milestone")
ts_iso  = os.environ["TS_ISO"]
html_path = os.environ["HTML_PATH"]
json_path = os.environ["JSON_PATH"]
state_dir = pathlib.Path(os.environ["DRAFT_STATE_DIR"])
rn       = os.environ.get("ROUND", "?")
actions  = [a.strip() for a in os.environ.get("ACTIONS", "Finalize,Cancel").split(",") if a.strip()]
outside_spend = os.environ.get("OUTSIDE_SPEND", "")

def read(name, default=""):
    p = state_dir / name
    return p.read_text() if p.exists() else default

understand = read("understand.yaml")
challenge  = read("challenge.yaml")
improver   = read("improver.yaml")
answers    = read("answers.md")

def esc(s): return html.escape(s or "")

# --- Parse current merged spec (cheap regex, not full YAML) ---
def extract(pat, text, default=""):
    m = re.search(pat, text, re.M)
    return m.group(1).strip() if m else default

def extract_list_block(header, text):
    # Matches  header:\n  - item\n  - item   OR  header: [a, b]
    m = re.search(rf'^{header}:\s*\[([^\]]*)\]', text, re.M)
    if m:
        return [s.strip().strip('"').strip("'") for s in m.group(1).split(",") if s.strip()]
    m = re.search(rf'^{header}:\s*\n((?:\s{{2,}}-\s*.+\n?)+)', text, re.M)
    if not m: return []
    return [re.sub(r'^\s*-\s*', '', line).strip() for line in m.group(1).splitlines() if line.strip()]

spec = {
    "in_scope":         extract_list_block("in_scope",         understand),
    "non_goals":        extract_list_block("non_goals",        understand),
    "success_criteria": extract_list_block("success_criteria", understand),
}
hours_low  = extract(r'^\s*hours_low:\s*(\d+)',  understand, "?")
hours_high = extract(r'^\s*hours_high:\s*(\d+)', understand, "?")
verdict    = extract(r'^verdict:\s*(.+)$',       challenge,  "SHIP_AS_SPECCED")

# --- Parse disagreements: each peer may emit a disagreements_with_others block ---
def parse_disagreements(text, owner):
    """Each block item under 'disagreements_with_others:' is a dict with other_agent/my_position/their_position/tradeoff/my_recommendation/rationale."""
    items = []
    m = re.search(r'^disagreements_with_others:\s*\n((?:\s{2,}.*\n?)*)', text, re.M)
    if not m: return items
    body = m.group(1)
    # Split on top-level list dashes (two-space indent common in our YAML)
    entries = re.split(r'\n(?=\s{2}-\s)', body)
    for i, e in enumerate(entries):
        if not e.strip(): continue
        def f(key):
            mm = re.search(rf'\b{key}:\s*(.+)', e)
            return mm.group(1).strip() if mm else ""
        items.append({
            "id": f"dis-{owner}-{i+1}",
            "owner": owner,
            "other_agent": f("other_agent"),
            "my_position": f("my_position"),
            "their_position": f("their_position"),
            "tradeoff": f("tradeoff"),
            "my_recommendation": f("my_recommendation"),
            "rationale": f("rationale"),
        })
    return items

disagreements = (parse_disagreements(understand, "understand")
               + parse_disagreements(challenge,  "challenge")
               + parse_disagreements(improver,   "improver"))

# --- Parse open questions from understand ---
open_qs = []
m = re.search(r'^open_questions:\s*\n((?:\s{2,}.*\n?)*)', understand, re.M)
if m:
    body = m.group(1)
    entries = re.split(r'\n(?=\s{2}-\s)', body)
    for e in entries:
        if not e.strip(): continue
        def f(key):
            mm = re.search(rf'\b{key}:\s*(.+)', e)
            return mm.group(1).strip() if mm else ""
        qid = f("id") or f"oq{len(open_qs)+1}"
        open_qs.append({
            "id": qid,
            "question": f("question"),
            "default_if_no_answer": f("default_if_no_answer"),
        })

# --- JSON sidecar (programmatic consumers) ---
payload = {
    "id": card_id,
    "kind": "draft-plan",
    "ts": ts_iso,
    "round": rn,
    "title": title,
    "outcome": outcome,
    "tier": tier,
    "verdict": verdict,
    "hours_low": hours_low,
    "hours_high": hours_high,
    "spec": spec,
    "disagreements": disagreements,
    "open_questions": open_qs,
    "refine_actions": ["ask", "pushback", "constrain"],
    "terminal_actions": ["finalize", "cancel"],
}
if ctx: payload["context_link"] = ctx
if outside_spend and outside_spend not in ("0","0.0","0.00"):
    try: payload["outside_spend_estimated_usd"] = float(outside_spend)
    except ValueError: payload["outside_spend_estimated_usd"] = outside_spend

with open(json_path, "w") as f:
    json.dump(payload, f, indent=2)

# --- HTML render ---
def bullets(items):
    if not items: return "<div class='muted'>(none)</div>"
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"

dis_html = ""
if disagreements:
    rows = []
    for d in disagreements:
        rows.append(f"""
        <div class="dis-row">
          <div class="dis-head"><span class="owner">[{esc(d['owner'])}]</span> vs <span class="owner">[{esc(d['other_agent'])}]</span> <span class="did">id: {esc(d['id'])}</span></div>
          <div class="dis-pos"><b>mine:</b> {esc(d['my_position'])}</div>
          <div class="dis-pos"><b>theirs:</b> {esc(d['their_position'])}</div>
          <div class="dis-trade"><b>tradeoff:</b> {esc(d['tradeoff'])}</div>
          <div class="dis-rec"><b>recommendation:</b> {esc(d['my_recommendation'])} &mdash; {esc(d['rationale'])}</div>
          <div class="dis-btns">
            <button class="btn btn-small" data-action="override" data-id="{esc(d['id'])}">Override — keep mine</button>
            <button class="btn btn-small" data-action="pushback" data-id="{esc(d['id'])}">Discuss — push back</button>
          </div>
        </div>""")
    dis_html = "<h2>Disagreements</h2>" + "".join(rows)
else:
    dis_html = "<h2>Disagreements</h2><div class='muted'>(none — agents concurred)</div>"

oq_html = ""
if open_qs:
    rows = []
    for q in open_qs:
        rows.append(f"""
        <div class="oq-row">
          <div class="oq-q"><b>{esc(q['id'])}:</b> {esc(q['question'])}</div>
          <div class="oq-def"><b>default-if-no-answer:</b> {esc(q['default_if_no_answer'])}</div>
          <div class="oq-btns"><button class="btn btn-small" data-action="answer" data-id="{esc(q['id'])}">Answer</button></div>
        </div>""")
    oq_html = "<h2>Open Questions</h2>" + "".join(rows)
else:
    oq_html = "<h2>Open Questions</h2><div class='muted'>(none open)</div>"

answers_html = ""
if answers.strip():
    answers_html = "<h2>Answers to direct questions</h2><pre class='answers'>" + esc(answers) + "</pre>"

spend_html = ""
if "outside_spend_estimated_usd" in payload:
    spend_html = f"<div class='field'><span class='lbl'>Outside spend (est.)</span><span class='val'>${payload['outside_spend_estimated_usd']}</span></div>"

ctx_html = ""
if ctx:
    ctx_html = f"<div class='field'><span class='lbl'>Report</span><a class='val link' href='{esc(ctx)}'>{esc(ctx)}</a></div>"

# Terminal buttons (Finalize, Cancel)
term_btns = []
for i, a in enumerate(actions):
    cls = "btn btn-primary" if a.lower() == "finalize" else ("btn btn-cancel" if a.lower() == "cancel" else "btn")
    term_btns.append(f'<button class="{cls}" data-action="{esc(a.lower())}" tabindex="{i+1}">{esc(a)}</button>')

page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Draft Plan r{esc(rn)}</title>
<style>
 :root {{ --fg:#111; --mut:#555; --bg:#fafafa; --card:#fff; --accent:#0b5fff; --cancel:#a33; --border:#e3e3e3; --warn:#e67e22; }}
 * {{ box-sizing:border-box; }}
 html,body {{ margin:0; padding:0; background:var(--bg); color:var(--fg);
              font:16px/1.45 -apple-system,system-ui,Segoe UI,Roboto,sans-serif; }}
 main {{ max-width:760px; margin:0 auto; padding:20px 16px 160px; }}
 h1 {{ font-size:22px; margin:4px 0 6px; }}
 h2 {{ font-size:16px; margin:18px 0 8px; color:var(--mut); text-transform:uppercase; letter-spacing:0.05em; }}
 .meta {{ color:var(--mut); font-size:13px; margin-bottom:12px; }}
 .round {{ display:inline-block; padding:2px 8px; border-radius:6px; background:var(--warn); color:#fff; font-size:12px; }}
 .outcome {{ font-size:17px; margin:0 0 14px; }}
 .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:18px; }}
 .field {{ display:flex; flex-direction:column; padding:8px 0; border-top:1px solid var(--border); }}
 .field .lbl {{ font-size:12px; color:var(--mut); text-transform:uppercase; letter-spacing:0.04em; }}
 .field .val {{ font-size:15px; word-break:break-all; }}
 .field .link {{ color:var(--accent); text-decoration:none; }}
 .muted {{ color:var(--mut); font-style:italic; }}
 ul {{ margin:6px 0 10px 20px; padding:0; }}
 .dis-row, .oq-row {{ border:1px solid var(--border); border-radius:8px; padding:12px; margin:8px 0; background:#fff; }}
 .dis-head {{ font-weight:600; margin-bottom:4px; }}
 .dis-head .owner {{ color:var(--accent); }}
 .dis-head .did {{ color:var(--mut); font-size:12px; float:right; }}
 .dis-pos, .dis-trade, .dis-rec {{ font-size:14px; margin:2px 0; }}
 .dis-btns, .oq-btns {{ margin-top:8px; display:flex; gap:8px; flex-wrap:wrap; }}
 .answers {{ background:#f3f3f3; padding:10px; border-radius:6px; font-size:13px; white-space:pre-wrap; }}
 .btn {{ min-height:44px; min-width:96px; padding:0 14px; font-size:15px;
         border-radius:10px; border:1px solid var(--border); background:#fff; color:var(--fg); cursor:pointer; }}
 .btn:focus {{ outline:3px solid var(--accent); outline-offset:2px; }}
 .btn-small {{ min-height:36px; min-width:0; font-size:13px; padding:0 10px; }}
 .btn-primary {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
 .btn-cancel {{ color:var(--cancel); }}
 .refine-row {{ display:flex; gap:8px; flex-wrap:wrap; margin:16px 0 8px; }}
 .terminal {{ position:fixed; left:0; right:0; bottom:0; background:var(--card);
              border-top:1px solid var(--border); padding:12px 16px; display:flex; gap:10px; justify-content:flex-end; }}
 @media (min-width:720px) {{
   main {{ padding:28px 24px 40px; }}
   .terminal {{ position:static; border:0; padding:16px 0 0; background:transparent; justify-content:flex-start; }}
 }}
</style>
</head>
<body>
<main>
  <div class="meta">Draft Plan · <span class="round">round r{esc(rn)}</span> · {esc(tier)} · {esc(ts_iso)} · id {esc(card_id)}</div>
  <h1>{esc(title)}</h1>
  <p class="outcome">{esc(outcome)}</p>
  <div class="card">
    <div class="field"><span class="lbl">Estimate</span><span class="val">{esc(hours_low)}-{esc(hours_high)} hours</span></div>
    <div class="field"><span class="lbl">Verdict</span><span class="val">{esc(verdict)}</span></div>
    {spend_html}
    {ctx_html}
    <h2>Current merged spec</h2>
    <div><b>In scope:</b>{bullets(spec['in_scope'])}</div>
    <div><b>Non-goals:</b>{bullets(spec['non_goals'])}</div>
    <div><b>Success criteria:</b>{bullets(spec['success_criteria'])}</div>
    {dis_html}
    {oq_html}
    {answers_html}
    <h2>Refine actions</h2>
    <div class="refine-row">
      <button class="btn" data-action="ask">Ask a question</button>
      <button class="btn" data-action="pushback">Push back on an item</button>
      <button class="btn" data-action="constrain">Add a constraint</button>
    </div>
    <div class="terminal" role="group" aria-label="Terminal actions">
      {"".join(term_btns)}
    </div>
  </div>
</main>
<script>
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Enter') {{ const p=document.querySelector('.btn-primary'); if(p) p.click(); }}
    else if (e.key === 'Escape') {{ const c=document.querySelector('.btn-cancel'); if(c) c.click(); }}
  }});
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
    # Milestone ntfy for draft-plan cards (same tier behaviour as default cards).
    if [ -x /etc/ntfy-topic ] || [ -s /etc/ntfy-topic ]; then
        "$SCRIPT_DIR/notify.sh" "$OUTCOME" "$TITLE — r$ROUND" --tier "$TIER" --click "$PUBLIC_URL" || true
    fi
    echo "$PUBLIC_URL"
    exit 0
fi

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
