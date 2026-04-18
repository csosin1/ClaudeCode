#!/bin/bash
# skills-shape-lint.sh — pre-commit hook.
#
# Every SKILLS/*.md must have "## When to use" (case-insensitive) as the first
# H2 after any optional YAML frontmatter block. Enforces on any staged change
# that touches SKILLS/*.md; also runs a full-tree scan and reports current
# drift count as a warning (never fails on pre-existing drift — only the
# staged files must pass).
#
# Rationale: "## When to use" is the highest-signal section of a skill. If
# it is missing or buried, consumers bounce. First H2 is structurally the
# right spot.

set -u
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$REPO_ROOT" || exit 2

check_file() {
  local f="$1"
  python3 - "$f" <<'PY'
import sys, pathlib, re
p = pathlib.Path(sys.argv[1])
if not p.exists():
    sys.exit(0)
lines = p.read_text().splitlines()
i = 0
# Skip optional YAML frontmatter
if i < len(lines) and lines[i].strip() == "---":
    i += 1
    while i < len(lines) and lines[i].strip() != "---":
        i += 1
    i += 1
# Find first H2
while i < len(lines):
    if lines[i].startswith("## "):
        first = lines[i].strip()
        ok = re.match(r'^## when to use\b', first, re.I) is not None
        print("OK" if ok else "DRIFT|" + first)
        sys.exit(0)
    i += 1
print("DRIFT|(no H2 found)")
PY
}

# --- Staged files: must pass ---
STAGED_FAIL=0
for f in $(git diff --cached --name-only --diff-filter=AM | grep -E '^SKILLS/.+\.md$' || true); do
  result=$(check_file "$f")
  if [ "$result" != "OK" ]; then
    echo "FAIL|$f|${result#DRIFT|}: first H2 must be '## When to use' (case-insensitive)"
    STAGED_FAIL=1
  fi
done

# --- Full-tree scan (warning only) ---
total=0
drift=0
drifting=()
for f in SKILLS/*.md; do
  [ -f "$f" ] || continue
  total=$((total+1))
  result=$(check_file "$f")
  if [ "$result" != "OK" ]; then
    drift=$((drift+1))
    drifting+=("$f|${result#DRIFT|}")
  fi
done

if [ "$drift" -gt 0 ] && [ "$STAGED_FAIL" = "0" ]; then
  echo "[skills-shape-lint] info: $drift/$total SKILLS/*.md missing '## When to use' as first H2 (not blocking — pre-existing drift)"
fi

if [ "$STAGED_FAIL" = "1" ]; then
  echo ""
  echo "Add '## When to use' as the first H2 (after any YAML frontmatter) with a 1-2 sentence"
  echo "description of when a consumer should invoke the skill."
  exit 1
fi

exit 0
