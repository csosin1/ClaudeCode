#!/bin/bash
# migrate-doc-frontmatter.sh — one-shot migration.
#
# Prepends YAML frontmatter (kind/last_verified/refresh_cadence/sunset) to
# durable platform docs that don't already have it. Touches:
#   - /opt/site-deploy/SKILLS/*.md               → kind: skill
#   - /opt/*/PROJECT_STATE.md  (top-level only)  → kind: project_state
#   - /opt/*/PROJECT_CONTEXT.md                  → kind: project_context
#   - /opt/site-deploy/RUNBOOK.md                → kind: runbook
#   - /opt/site-deploy/MIGRATION_RUNBOOK.md      → kind: runbook
#
# LESSONS.md is entry-level — migration for that lives at the end of this
# script and uses HTML-comment per-entry blocks (see lessons-lint.sh).
#
# Activity-gated freshness: refresh_cadence defaults to "on_touch". There is
# NO background cron comparing last_verified to wall clock. A doc sitting
# untouched during project dormancy is NOT stale. See SKILLS/doc-frontmatter.md.
#
# Idempotent: re-running skips files that already carry frontmatter.

set -eu
TODAY="$(date +%Y-%m-%d)"

have_frontmatter() {
  # Returns 0 if file's first non-empty line is '---'
  python3 -c '
import sys, pathlib
p = pathlib.Path(sys.argv[1])
if not p.exists(): sys.exit(1)
for line in p.read_text().splitlines():
    s = line.strip()
    if not s: continue
    sys.exit(0 if s == "---" else 1)
sys.exit(1)
' "$1"
}

prepend_frontmatter() {
  local file="$1" kind="$2"
  if have_frontmatter "$file"; then
    echo "skip (has frontmatter): $file"
    return 0
  fi
  python3 - "$file" "$kind" "$TODAY" <<'PY'
import sys, pathlib
f, kind, today = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(f)
body = p.read_text()
fm = (
    "---\n"
    f"kind: {kind}\n"
    f"last_verified: {today}\n"
    "refresh_cadence: on_touch\n"
    "sunset: null\n"
    "---\n"
)
p.write_text(fm + body)
PY
  echo "wrote: $file ($kind)"
}

# --- SKILLS ---
for f in /opt/site-deploy/SKILLS/*.md; do
  [ -f "$f" ] || continue
  prepend_frontmatter "$f" skill
done

# --- RUNBOOK + MIGRATION_RUNBOOK ---
for f in /opt/site-deploy/RUNBOOK.md /opt/site-deploy/MIGRATION_RUNBOOK.md; do
  [ -f "$f" ] || continue
  prepend_frontmatter "$f" runbook
done

# --- PROJECT_STATE / PROJECT_CONTEXT ---
for f in /opt/*/PROJECT_STATE.md; do
  [ -f "$f" ] || continue
  prepend_frontmatter "$f" project_state
done
for f in /opt/*/PROJECT_CONTEXT.md; do
  [ -f "$f" ] || continue
  prepend_frontmatter "$f" project_context
done

# --- LESSONS.md entries (per-entry HTML-comment frontmatter) ---
# Walks each "## YYYY-MM-DD ..." header; if no <!--lesson ... --> block
# follows, inserts one with sensible defaults. Caller is expected to
# hand-tune the preventive_mechanism / enforcer_path / family afterwards.
LESSONS=/opt/site-deploy/LESSONS.md
if [ -f "$LESSONS" ]; then
  python3 - "$LESSONS" "$TODAY" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1])
today = sys.argv[2]
lines = p.read_text().splitlines()
out = []
i = 0
inserted = 0
while i < len(lines):
    line = lines[i]
    m = re.match(r'^## \[?(\d{4}-\d{2}-\d{2})\]?', line)
    if not m:
        out.append(line)
        i += 1
        continue
    out.append(line)
    date = m.group(1)
    # Peek ahead — skip blank lines, then see if a <!--lesson block is present
    j = i + 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    already = j < len(lines) and lines[j].strip() == "<!--lesson"
    if already:
        # copy through the block verbatim
        i = i + 1
        continue
    # Insert a default block with preventive_mechanism: doc_only
    out.extend([
        "",
        "<!--lesson",
        "preventive_mechanism: doc_only",
        "enforcer_path: none",
        f"date: {date}",
        "family: unclassified",
        "-->",
    ])
    inserted += 1
    i += 1

p.write_text("\n".join(out) + "\n")
print(f"LESSONS.md: inserted {inserted} per-entry frontmatter block(s)", file=sys.stderr)
PY
fi

echo "migration complete."
