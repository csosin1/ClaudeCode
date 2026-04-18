#!/usr/bin/env bash
# visual-review-orchestrator.sh — run the A-llm semantic visual QA layer
#
# Invoked from a project's qa.yml (or locally during development).
# For each declared page × viewport, dispatches two visual-reviewer
# subagents in parallel (briefed + unbriefed), collects their JSON
# findings, merges them, appends to /var/log/<project>-visual-review.jsonl,
# and exits non-zero if any finding has severity HALT.
#
# Inputs:
#   $1  project slug (e.g. "abs-dashboard")
#   $2  path to REVIEW_CONTEXT.md in the project
#   $3  path to the pages list (YAML or newline-delimited URL\tviewport pairs)
#        - if the file is named *.perf.yaml we parse `pages:` from it
#        - otherwise treat as newline-delimited "URL<TAB>VIEWPORT"
#   $4  (optional) path to the writing agent's change brief — if omitted,
#        only the unbriefed reviewer runs per page
#
# Environment:
#   BASE_URL           — prepended to relative page paths (default http://159.223.127.125)
#   SCREENSHOT_DIR     — where Playwright screenshots are written (default /tmp/visual-qa-<project>)
#   REVIEW_LOG         — override the JSONL append target
#   CLAUDE_BIN         — path to claude CLI (default: claude)
#
# Exit codes:
#   0  — no HALT findings; ship-safe
#   1  — at least one HALT finding; gate should fail
#   2  — orchestrator error (missing inputs, dispatch failure)
#
# Parallelization: screenshots are serial (Playwright owns the browser);
# reviewer dispatches are parallel per (page × viewport × mode).

set -eE -o pipefail
trap 'echo "[visual-review-orchestrator] ERROR line $LINENO (exit=$?)" >&2' ERR

PROJECT="${1:-}"
CONTEXT_PATH="${2:-}"
PAGES_PATH="${3:-}"
BRIEF_PATH="${4:-}"

if [[ -z "$PROJECT" || -z "$CONTEXT_PATH" || -z "$PAGES_PATH" ]]; then
  echo "usage: $0 <project> <REVIEW_CONTEXT.md> <pages-file> [brief-file]" >&2
  exit 2
fi
if [[ ! -f "$CONTEXT_PATH" ]]; then
  echo "[visual-review-orchestrator] REVIEW_CONTEXT.md not found: $CONTEXT_PATH" >&2
  exit 2
fi
if [[ ! -f "$PAGES_PATH" ]]; then
  echo "[visual-review-orchestrator] pages file not found: $PAGES_PATH" >&2
  exit 2
fi

BASE_URL="${BASE_URL:-http://159.223.127.125}"
SCREENSHOT_DIR="${SCREENSHOT_DIR:-/tmp/visual-qa-${PROJECT}}"
REVIEW_LOG="${REVIEW_LOG:-/var/log/${PROJECT}-visual-review.jsonl}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"

mkdir -p "$SCREENSHOT_DIR"
# Ensure the log file is writable (fall back to /tmp if /var/log is not writable).
if ! touch "$REVIEW_LOG" 2>/dev/null; then
  REVIEW_LOG="/tmp/${PROJECT}-visual-review.jsonl"
  touch "$REVIEW_LOG"
fi

TMPDIR_RUN="$(mktemp -d "/tmp/visual-review-${PROJECT}.XXXXXX")"
trap 'rm -rf "$TMPDIR_RUN"' EXIT

# ---------------------------------------------------------------------------
# Parse pages file.
# Format A (preferred): newline-delimited "PATH\tVIEWPORT" where VIEWPORT is
#                       390 or 1280. Blank lines and # comments are ignored.
# Format B: .perf.yaml with a top-level `pages:` list of mappings
#           `- path: /foo` and `viewports: [390, 1280]`.
# ---------------------------------------------------------------------------

PAGES_RESOLVED="$TMPDIR_RUN/pages.tsv"
: > "$PAGES_RESOLVED"

if [[ "$PAGES_PATH" == *.yaml || "$PAGES_PATH" == *.yml ]]; then
  # Minimal YAML parse — avoid a dependency on yq. Lines starting with
  # "- path:" produce a row for each viewport on the preceding/following
  # `viewports:` line. Degenerate but sufficient for our .perf.yaml shape.
  python3 - "$PAGES_PATH" "$PAGES_RESOLVED" <<'PYEOF'
import sys, re, pathlib
src = pathlib.Path(sys.argv[1]).read_text()
out = pathlib.Path(sys.argv[2])
# Walk the YAML textually. Record (path, [viewports]) tuples.
pages = []
current = None
for raw in src.splitlines():
    line = raw.rstrip()
    m = re.match(r"\s*-\s*path:\s*(\S+)\s*$", line)
    if m:
        if current: pages.append(current)
        current = {"path": m.group(1), "viewports": []}
        continue
    m = re.match(r"\s*viewports?:\s*\[([^\]]+)\]\s*$", line)
    if m and current is not None:
        current["viewports"] = [v.strip() for v in m.group(1).split(",") if v.strip()]
        continue
if current: pages.append(current)
rows = []
for p in pages:
    vs = p["viewports"] or ["390", "1280"]
    for v in vs:
        rows.append(f"{p['path']}\t{v}")
out.write_text("\n".join(rows) + ("\n" if rows else ""))
PYEOF
else
  grep -Ev '^\s*(#|$)' "$PAGES_PATH" > "$PAGES_RESOLVED" || true
fi

PAGE_COUNT=$(wc -l < "$PAGES_RESOLVED" | tr -d ' ')
if [[ "$PAGE_COUNT" == "0" ]]; then
  echo "[visual-review-orchestrator] no pages resolved from $PAGES_PATH — nothing to review" >&2
  exit 2
fi

echo "[visual-review-orchestrator] project=$PROJECT pages=$PAGE_COUNT log=$REVIEW_LOG brief=${BRIEF_PATH:-<none>}"

# ---------------------------------------------------------------------------
# Screenshot capture — serial, one browser at a time.
# ---------------------------------------------------------------------------

SCREENSHOT_SCRIPT="$TMPDIR_RUN/capture.js"
cat > "$SCREENSHOT_SCRIPT" <<'JSEOF'
// Minimal Playwright screenshot capture. Reads PAGES_TSV, writes PNGs into OUT_DIR.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const baseUrl = process.env.BASE_URL;
const outDir = process.env.OUT_DIR;
const tsv = fs.readFileSync(process.env.PAGES_TSV, 'utf8');
const rows = tsv.split('\n').filter(l => l.trim().length > 0).map(l => {
  const [p, v] = l.split('\t');
  return { path: p, viewport: parseInt(v, 10) };
});

(async () => {
  const browser = await chromium.launch();
  for (const r of rows) {
    const url = r.path.startsWith('http') ? r.path : (baseUrl.replace(/\/$/, '') + r.path);
    const ctx = await browser.newContext({ viewport: { width: r.viewport, height: 900 } });
    const page = await ctx.newPage();
    try {
      await page.goto(url, { waitUntil: 'networkidle', timeout: 20000 });
    } catch (e) {
      console.error(`[capture] goto failed ${url}: ${e.message}`);
    }
    const safe = r.path.replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '') || 'index';
    const file = path.join(outDir, `${safe}_${r.viewport}.png`);
    await page.screenshot({ path: file, fullPage: true });
    console.log(`[capture] ${r.path} @ ${r.viewport} -> ${file}`);
    await ctx.close();
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(3); });
JSEOF

if ! command -v node >/dev/null 2>&1; then
  echo "[visual-review-orchestrator] node is not installed; cannot capture screenshots" >&2
  exit 2
fi

BASE_URL="$BASE_URL" OUT_DIR="$SCREENSHOT_DIR" PAGES_TSV="$PAGES_RESOLVED" \
  node "$SCREENSHOT_SCRIPT" || {
    echo "[visual-review-orchestrator] screenshot capture failed" >&2
    exit 2
  }

# ---------------------------------------------------------------------------
# Dispatch reviewers in parallel.
#
# Each (page × viewport × mode) produces one findings JSON in
# $TMPDIR_RUN/findings/<page>_<viewport>_<mode>.json
# ---------------------------------------------------------------------------

mkdir -p "$TMPDIR_RUN/findings"
REVIEW_CONTEXT_CONTENT="$(cat "$CONTEXT_PATH")"
BRIEF_CONTENT=""
if [[ -n "$BRIEF_PATH" && -f "$BRIEF_PATH" ]]; then
  BRIEF_CONTENT="$(cat "$BRIEF_PATH")"
fi

dispatch_one() {
  local page="$1" viewport="$2" mode="$3" shot="$4" outfile="$5"
  local prompt_file="$TMPDIR_RUN/prompt_$(basename "$outfile" .json).txt"

  {
    echo "You are the visual-reviewer subagent (see .claude/agents/visual-reviewer.md)."
    echo "Mode: $mode"
    echo "Page: $page"
    echo "Viewport: $viewport"
    echo "Screenshot path on disk: $shot"
    echo ""
    echo "=== REVIEW_CONTEXT.md (project: $PROJECT) ==="
    echo "$REVIEW_CONTEXT_CONTENT"
    if [[ "$mode" == "briefed" && -n "$BRIEF_CONTENT" ]]; then
      echo ""
      echo "=== WRITING AGENT BRIEF ==="
      echo "$BRIEF_CONTENT"
    fi
    echo ""
    echo "Emit ONLY the JSON findings object described in your agent spec. No preamble."
  } > "$prompt_file"

  # If claude CLI is unavailable (e.g. CI without credentials), emit an
  # empty findings object so the gate is non-blocking but the log row
  # records the skip.
  if ! command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
    jq -cn --arg m "$mode" --arg p "$page" --arg v "$viewport" \
      '{findings: [], overall_verdict: "PASS", reviewed_with_brief: ($m=="briefed"), skipped: true, reason: "claude CLI unavailable"}' \
      > "$outfile"
    return 0
  fi

  # Dispatch in headless mode. --output-format json returns the agent's
  # final text as the .result field.
  local raw
  if ! raw="$("$CLAUDE_BIN" -p --agent visual-reviewer --output-format json < "$prompt_file" 2>/dev/null)"; then
    jq -cn --arg m "$mode" --arg p "$page" --arg v "$viewport" \
      '{findings: [], overall_verdict: "PASS", reviewed_with_brief: ($m=="briefed"), skipped: true, reason: "dispatch failed"}' \
      > "$outfile"
    return 0
  fi

  # Extract the model's JSON. Try .result first (claude CLI wrapper), then
  # treat raw as the object itself.
  local body
  body="$(jq -r '.result // empty' <<<"$raw" 2>/dev/null || true)"
  if [[ -z "$body" ]]; then body="$raw"; fi
  # Strip code fences if present.
  body="$(sed -E 's/^```(json)?//; s/```$//' <<<"$body")"

  if ! jq -e . <<<"$body" >/dev/null 2>&1; then
    jq -cn --arg m "$mode" --arg p "$page" --arg v "$viewport" --arg raw "$body" \
      '{findings: [], overall_verdict: "PASS_WITH_NOTES", reviewed_with_brief: ($m=="briefed"), parse_error: true, raw: $raw[:400]}' \
      > "$outfile"
    return 0
  fi

  jq --arg m "$mode" --arg p "$page" --arg v "$viewport" \
    '. + {mode: $m, page: $p, viewport: $v}' <<<"$body" > "$outfile"
}

export -f dispatch_one
export TMPDIR_RUN PROJECT REVIEW_CONTEXT_CONTENT BRIEF_CONTENT CLAUDE_BIN

PIDS=()
while IFS=$'\t' read -r PATH_ VIEWPORT; do
  [[ -z "$PATH_" ]] && continue
  safe="$(tr -c 'a-zA-Z0-9' '_' <<<"$PATH_" | sed -E 's/^_+|_+$//g')"
  [[ -z "$safe" ]] && safe="index"
  shot="$SCREENSHOT_DIR/${safe}_${VIEWPORT}.png"

  for MODE in unbriefed briefed; do
    # Skip briefed dispatch if no brief provided.
    if [[ "$MODE" == "briefed" && -z "$BRIEF_CONTENT" ]]; then continue; fi
    outfile="$TMPDIR_RUN/findings/${safe}_${VIEWPORT}_${MODE}.json"
    ( dispatch_one "$PATH_" "$VIEWPORT" "$MODE" "$shot" "$outfile" ) &
    PIDS+=($!)
  done
done < "$PAGES_RESOLVED"

for pid in "${PIDS[@]}"; do wait "$pid" || true; done

# ---------------------------------------------------------------------------
# Merge + report.
# ---------------------------------------------------------------------------

MERGED="$TMPDIR_RUN/merged.json"
jq -s '.' "$TMPDIR_RUN/findings"/*.json > "$MERGED"

TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
while IFS=$'\t' read -r PATH_ VIEWPORT; do
  [[ -z "$PATH_" ]] && continue
  safe="$(tr -c 'a-zA-Z0-9' '_' <<<"$PATH_" | sed -E 's/^_+|_+$//g')"
  [[ -z "$safe" ]] && safe="index"
  for MODE in unbriefed briefed; do
    f="$TMPDIR_RUN/findings/${safe}_${VIEWPORT}_${MODE}.json"
    [[ -f "$f" ]] || continue
    br=$(jq -r '[.findings[]? | select(.severity=="HALT")] | length' "$f")
    wr=$(jq -r '[.findings[]? | select(.severity=="WARN")] | length' "$f")
    echo "[visual-review] $PATH_  vp=$VIEWPORT  mode=$MODE  HALT=$br  WARN=$wr"
    jq -c --arg ts "$TIMESTAMP" --arg project "$PROJECT" \
      '. + {ts: $ts, project: $project}' "$f" >> "$REVIEW_LOG"
  done
done < "$PAGES_RESOLVED"

TOTAL_HALT=$(jq '[.[].findings[]? | select(.severity=="HALT")] | length' "$MERGED")
TOTAL_WARN=$(jq '[.[].findings[]? | select(.severity=="WARN")] | length' "$MERGED")
echo "[visual-review-orchestrator] summary: HALT=$TOTAL_HALT WARN=$TOTAL_WARN log=$REVIEW_LOG"

if [[ "$TOTAL_HALT" -gt 0 ]]; then
  echo "[visual-review-orchestrator] FAIL — $TOTAL_HALT HALT finding(s)" >&2
  exit 1
fi

exit 0
