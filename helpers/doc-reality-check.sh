#!/bin/bash
# doc-reality-check.sh — pre-commit hook.
#
# Scans *staged* changes to CHANGES.md and LESSONS.md for path-looking strings
# in backticks and asserts each claimed artifact exists on disk. Catches the
# 2026-04-17 class bug where CHANGES claimed post-deploy-qa-hook shipped but
# the files were not on disk.
#
# Extraction rule:
#   - Only staged ADDED lines (the `+` side of the diff) in CHANGES.md / LESSONS.md.
#   - Backtick-wrapped tokens containing `/` or starting with a known prefix
#     (SKILLS/, helpers/, deploy/, tests/, .claude/, /opt/, /etc/, /usr/local/,
#     /var/) and ending in a plausible filename/dir are candidates.
#   - Tokens with globs (`*`), regex chars (`?` / `[`), placeholders
#     (`<project>`, `<slug>`, `<topic>`, `<token>`, `YYYY-...`, `...`), env
#     vars (`$foo`), or trailing colons are skipped — they're illustrative,
#     not load-bearing.
#   - Command fragments (contain a space) are skipped.
#
# Exit: 0 if all extracted paths exist; non-zero with list of missing paths.
# Treat all checked paths as relative to the repo root (the cwd of git hooks).

set -u
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "[doc-reality-check] not in a git repo"; exit 0; }
cd "$REPO_ROOT" || exit 2

TARGETS=()
for f in CHANGES.md LESSONS.md; do
  if git diff --cached --name-only | grep -qx "$f"; then
    TARGETS+=("$f")
  fi
done

if [ "${#TARGETS[@]}" -eq 0 ]; then
  exit 0
fi

missing=()
for f in "${TARGETS[@]}"; do
  # Added lines only (starting with `+` but not `+++`). Extract backticked tokens.
  git diff --cached -U0 -- "$f" \
    | awk '/^\+[^+]/ {print substr($0,2)}' \
    | grep -oE '`[^`]+`' \
    | sed 's/^`//; s/`$//' \
    | while IFS= read -r tok; do
        # Filter obvious non-paths
        [ -z "$tok" ] && continue
        case "$tok" in
          *" "*) continue ;;                # command fragment
          *'*'*|*'?'*|*'['*) continue ;;    # glob/regex
          *'<'*'>'*) continue ;;            # placeholder <slug>
          *'$'*) continue ;;                # variable
          *'...'*) continue ;;              # ellipsis
          YYYY*|*:YYYY*) continue ;;
          *:) continue ;;                   # trailing colon
        esac
        # Only consider strings that look like a filesystem path.
        # Key filter: must contain a '/' (so bare filenames used as type
        # references — 'CHANGES.md', 'LESSONS.md', 'PROJECT_STATE.md' — are
        # treated as prose tokens, not paths). Absolute paths and prefixed
        # relative paths both contain slashes; genuine type-references don't.
        case "$tok" in
          */*) ;;       # contains a slash — treat as a path claim
          *) continue ;; # no slash — treat as prose (type reference, label)
        esac
        # Strip trailing punctuation that sometimes leaks in
        tok="${tok%.}"
        tok="${tok%,}"
        tok="${tok%;}"
        # If it starts with /, check absolute. Else relative to repo root.
        if [ "${tok:0:1}" = "/" ]; then
          target="$tok"
        else
          target="$REPO_ROOT/$tok"
        fi
        if [ ! -e "$target" ]; then
          echo "MISSING|$f|$tok"
        fi
      done
done > /tmp/.doc-reality-check.$$

if [ -s /tmp/.doc-reality-check.$$ ]; then
  echo ""
  echo "[doc-reality-check] staged docs claim artifacts that are NOT on disk:"
  echo ""
  awk -F'|' '{printf "  %-14s %s\n", $2":", $3}' /tmp/.doc-reality-check.$$
  echo ""
  echo "Either:"
  echo "  (a) stage the missing files along with the doc entry, or"
  echo "  (b) rewrite the entry so the token is not in backticks (prose, not path claim)."
  rm -f /tmp/.doc-reality-check.$$
  exit 1
fi

rm -f /tmp/.doc-reality-check.$$
exit 0
