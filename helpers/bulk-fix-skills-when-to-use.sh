#!/bin/bash
# bulk-fix-skills-when-to-use.sh — one-shot fixer.
#
# For every SKILLS/*.md whose first post-frontmatter H2 is not
# "## When to use" (case-insensitive), insert a one-sentence placeholder
# "## When to use" block immediately before the existing first H2. Content
# is a generic one-liner derived from the file's H1 — a human is expected
# to sharpen these later.
#
# Idempotent: skips files whose first H2 is already "## When to use".

set -eu
for f in /opt/site-deploy/SKILLS/*.md; do
  [ -f "$f" ] || continue
  python3 - "$f" <<'PY'
import sys, pathlib, re
p = pathlib.Path(sys.argv[1])
lines = p.read_text().splitlines()
i = 0
# Skip frontmatter
if i < len(lines) and lines[i].strip() == "---":
    i += 1
    while i < len(lines) and lines[i].strip() != "---":
        i += 1
    i += 1
# Find first H2
h2_idx = None
while i < len(lines):
    if lines[i].startswith("## "):
        h2_idx = i
        break
    i += 1
if h2_idx is None:
    print(f"no H2 found: {p.name}", file=sys.stderr)
    sys.exit(0)
if re.match(r'^## when to use\b', lines[h2_idx].strip(), re.I):
    sys.exit(0)  # already compliant
# Find H1 text for context
h1 = ""
for L in lines:
    m = re.match(r'^#\s+(.*)$', L)
    if m:
        h1 = m.group(1).strip()
        break
topic = re.sub(r'^(Skill|SKILL):\s*', '', h1, flags=re.I).strip() or p.stem
# Build the insertion
placeholder = [
    "## When to use",
    "",
    f"Use this skill when working on {topic.lower()}. "
    f"(Placeholder — sharpen with the specific triggers: which tasks, which error modes, "
    f"which project phases invoke it.)",
    "",
]
new_lines = lines[:h2_idx] + placeholder + lines[h2_idx:]
p.write_text("\n".join(new_lines) + ("\n" if not new_lines[-1].endswith("\n") else ""))
print(f"fixed: {p.name}", file=sys.stderr)
PY
done
