#!/bin/bash
# refresh-docs.sh — mirror the allow-listed subset of /opt/site-deploy/ into /var/www/docs/
# for the advisor-docs endpoint at https://casinv.dev/docs/
# Idempotent; safe to run on every deploy. Regenerates bundle chunks + index.html.
set -e

SRC=/opt/site-deploy
DST=/var/www/docs

mkdir -p "$DST"/{skills,reflections,bundle-chunks,helpers/infra-home,migration-inventory}

# Allow-list: explicit file-by-file copy. Never a blanket rsync.
cp "$SRC/CLAUDE.md"           "$DST/CLAUDE.md"
cp "$SRC/LESSONS.md"          "$DST/LESSONS.md"
cp "$SRC/RUNBOOK.md"          "$DST/RUNBOOK.md"
cp "$SRC/ADVISOR_CONTEXT.md"  "$DST/ADVISOR_CONTEXT.md"
cp "$SRC/MIGRATION_RUNBOOK.md" "$DST/MIGRATION_RUNBOOK.md" 2>/dev/null || true
cp "$SRC"/SKILLS/*.md         "$DST/skills/"
cp "$SRC"/reflections/*.md    "$DST/reflections/" 2>/dev/null || true
cp "$SRC"/helpers/infra-home/*.md "$DST/helpers/infra-home/" 2>/dev/null || true
cp "$SRC"/helpers/migration-inventory-*.md "$DST/migration-inventory/" 2>/dev/null || true

# Explicitly NOT copied: ACCOUNTS.md, .env*, *.sh scripts, project source dirs, CHANGES.md,
# .git metadata. If it isn't in the list above, it isn't served.

# Re-split ADVISOR_BUNDLE.md into <50 KB chunks if source changed.
if [ -f "$SRC/ADVISOR_BUNDLE.md" ]; then
    python3 - <<'PY'
from pathlib import Path
import re
src = Path('/opt/site-deploy/ADVISOR_BUNDLE.md').read_text()
out = Path('/var/www/docs/bundle-chunks')
out.mkdir(exist_ok=True, parents=True)
# Clear old chunks
for f in out.glob('chunk-*.md'):
    f.unlink()
pattern = re.compile(r'(?=^=+\s*\n## \d+\. )', re.MULTILINE)
parts = pattern.split(src)
chunks = []
cur = parts[0]
for p in parts[1:]:
    if len(cur.encode('utf-8')) + len(p.encode('utf-8')) < 50 * 1024:
        cur += p
    else:
        chunks.append(cur); cur = p
if cur: chunks.append(cur)
def explode(s):
    bs = re.split(r'(?=^### )', s, flags=re.MULTILINE)
    r = []; cur = bs[0]
    for b in bs[1:]:
        if len(cur.encode('utf-8')) + len(b.encode('utf-8')) < 50 * 1024: cur += b
        else: r.append(cur); cur = "(continued from previous chunk)\n\n" + b
    if cur: r.append(cur)
    return r
expanded = []
for c in chunks:
    if '## 3. SKILLS' in c and len(c.encode('utf-8')) > 50 * 1024:
        expanded.extend(explode(c))
    else:
        expanded.append(c)
def safe(text, n=40):
    s = text.lower().replace('/', '-').replace('_', '-').replace(' ', '-').replace(',', '')
    s = re.sub(r'[^a-z0-9\-]', '', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s[:n] or 'section'
for i, c in enumerate(expanded, 1):
    m = re.search(r'^## \d+\. ([A-Z_\- ,]+)', c, re.MULTILINE)
    if m: label = safe(m.group(1))
    else:
        m2 = re.search(r'^### .*/([a-z\-]+)\.md', c, re.MULTILINE) or re.search(r'^### ([^\n]+)', c, re.MULTILINE)
        label = safe(m2.group(1)) if m2 else 'intro'
    (out / f'chunk-{i:02d}-{label}.md').write_text(c)
PY
fi

# Update the refresh timestamp in index.html
NOW=$(date -u +'%Y-%m-%d %H:%M UTC')
sed -i "s|<code id=\"refresh\">.*</code>|<code id=\"refresh\">$NOW</code>|" "$DST/index.html" 2>/dev/null || true

# Permissions: root:www-data, readable by nginx
chown -R root:www-data "$DST" 2>/dev/null || true
chmod -R 640 "$DST"
find "$DST" -type d -exec chmod 750 {} \;

echo "docs refreshed at $NOW"
