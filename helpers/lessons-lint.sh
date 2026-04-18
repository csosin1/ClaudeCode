#!/bin/bash
# lessons-lint.sh — pre-commit hook.
#
# Enforces per-entry YAML frontmatter on LESSONS.md and nags on stale doc-only
# entries. Frontmatter format (one block immediately after the "## YYYY-MM-DD"
# header line):
#
#   <!--lesson
#   preventive_mechanism: code_assert | ci_gate | pre_commit | reviewer_rule | doc_only | doc_only_accepted
#   enforcer_path: <path or "none">
#   date: YYYY-MM-DD
#   family: <short tag, e.g. state-drift, parallel-dispatch, sequential-cognitive>
#   -->
#
# (HTML comment wrapper keeps the block invisible in rendered markdown while
# being trivially parseable.)
#
# Failure conditions (exit 1):
#   - A staged ADD of a new "## YYYY-..." header in LESSONS.md without a
#     following lesson-frontmatter block.
#   - A lesson-frontmatter block is present but missing a required key, or
#     preventive_mechanism has an unknown value.
#
# Warning-only (stderr, never fail):
#   - doc_only entries older than 14 days — suggest promoting to a stronger
#     tier OR tagging doc_only_accepted. Rarity is a feature; never retire on
#     frequency or dormancy.

set -u
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$REPO_ROOT" || exit 2

LESSONS="LESSONS.md"
[ -f "$LESSONS" ] || exit 0

VALID_MECH="code_assert ci_gate pre_commit reviewer_rule doc_only doc_only_accepted"

# --- Parse LESSONS.md into (header_line, date, frontmatter_keys) records ------
python3 - <<'PY' > /tmp/.lessons-parsed.$$
import re, sys, pathlib, datetime, json

p = pathlib.Path("LESSONS.md")
lines = p.read_text().splitlines()
entries = []
i = 0
while i < len(lines):
    m = re.match(r'^## \[?(\d{4}-\d{2}-\d{2})\]?', lines[i])
    if not m:
        i += 1
        continue
    date = m.group(1)
    header_line = i + 1  # 1-indexed
    # Look for frontmatter within the next 20 lines
    fm = {}
    has_fm = False
    j = i + 1
    while j < len(lines) and j < i + 25:
        if lines[j].strip() == "":
            j += 1
            continue
        if lines[j].strip() == "<!--lesson":
            has_fm = True
            j += 1
            while j < len(lines) and lines[j].strip() != "-->":
                mm = re.match(r'^\s*([a-z_]+):\s*(.*?)\s*$', lines[j])
                if mm:
                    fm[mm.group(1)] = mm.group(2)
                j += 1
            break
        # Non-blank non-frontmatter line → no frontmatter
        break
    entries.append({"date": date, "line": header_line, "has_fm": has_fm, "fm": fm,
                    "title": lines[i][3:].strip()})
    i = j + 1 if has_fm else i + 1

print(json.dumps(entries))
PY
PARSED=$(cat /tmp/.lessons-parsed.$$)
rm -f /tmp/.lessons-parsed.$$

# --- FAIL: any entry missing frontmatter or with invalid keys ----------------
FAIL=0
TODAY=$(date +%Y-%m-%d)
TODAY_EPOCH=$(date -d "$TODAY" +%s)

# Which entries were touched by this commit? (by header line number being in the staged diff)
STAGED_LINES=$(git diff --cached -U0 -- "$LESSONS" | grep -E '^@@' \
  | sed -E 's/^@@ -[0-9]+(,[0-9]+)? \+([0-9]+).*/\2/' || true)

# Only enforce on entries that appear in the staged diff's ADD range.
# If the commit doesn't touch LESSONS.md, exit 0 (no enforcement).
if ! git diff --cached --name-only | grep -qx "$LESSONS"; then
  # File not staged — run the nag pass only (informational), still exit 0.
  STAGED_MODE=0
else
  STAGED_MODE=1
fi

# Added lesson headers (new entries) — these MUST have frontmatter.
NEW_HEADERS=$(git diff --cached -U0 -- "$LESSONS" \
  | awk '/^\+[^+]/ {print substr($0,2)}' \
  | grep -cE '^## \[?[0-9]{4}-[0-9]{2}-[0-9]{2}' || true)

if [ "$STAGED_MODE" = "1" ]; then
  python3 - "$PARSED" "$NEW_HEADERS" <<'PY'
import json, sys, subprocess, re
entries = json.loads(sys.argv[1])
valid = set("code_assert ci_gate pre_commit reviewer_rule doc_only doc_only_accepted".split())
required = {"preventive_mechanism", "enforcer_path", "date", "family"}

# Gather added lesson headers (title text) from the staged diff
added_titles = set()
diff = subprocess.check_output(["git", "diff", "--cached", "-U0", "--", "LESSONS.md"]).decode()
for line in diff.splitlines():
    if line.startswith("+") and not line.startswith("+++"):
        m = re.match(r'^\+## \[?(\d{4}-\d{2}-\d{2})\]?\s*—?\s*(.*)$', line)
        if m:
            added_titles.add(line[3:].strip())

fail = 0
for e in entries:
    if e["title"] not in added_titles:
        continue
    if not e["has_fm"]:
        print(f"FAIL|line {e['line']}|new lesson '{e['title'][:60]}' missing <!--lesson ... --> frontmatter", file=sys.stderr)
        fail = 1
        continue
    missing = required - set(e["fm"].keys())
    if missing:
        print(f"FAIL|line {e['line']}|lesson '{e['title'][:60]}' missing keys: {sorted(missing)}", file=sys.stderr)
        fail = 1
    mech = e["fm"].get("preventive_mechanism")
    if mech and mech not in valid:
        print(f"FAIL|line {e['line']}|preventive_mechanism='{mech}' not in {sorted(valid)}", file=sys.stderr)
        fail = 1

sys.exit(1 if fail else 0)
PY
  FAIL=$?
fi

# --- NAG: doc_only entries older than 14 days --------------------------------
# Never fail, just warn.
python3 - "$PARSED" <<'PY'
import json, sys, datetime
entries = json.loads(sys.argv[1])
today = datetime.date.today()
nags = []
for e in entries:
    if not e["has_fm"]:
        continue
    if e["fm"].get("preventive_mechanism") != "doc_only":
        continue
    try:
        d = datetime.date.fromisoformat(e["fm"].get("date", e["date"]))
    except Exception:
        continue
    age = (today - d).days
    if age >= 14:
        nags.append((age, e["title"][:70], e["line"]))
if nags:
    print("", file=sys.stderr)
    print(f"[lessons-lint] {len(nags)} doc_only lesson(s) older than 14 days:", file=sys.stderr)
    for age, title, line in sorted(nags, reverse=True):
        print(f"  line {line:4d} ({age:3d}d)  {title}", file=sys.stderr)
    print("", file=sys.stderr)
    print("  Consider promoting (code_assert > ci_gate > pre_commit > reviewer_rule)", file=sys.stderr)
    print("  OR tag as 'doc_only_accepted' if intentionally long-tail.", file=sys.stderr)
    print("  See SKILLS/lesson-promotion.md. (Warning only — never fails.)", file=sys.stderr)
PY

exit $FAIL
