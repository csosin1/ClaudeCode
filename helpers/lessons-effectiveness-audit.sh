#!/bin/bash
# lessons-effectiveness-audit.sh — did the patterns LESSONS entries warn about recur?
#
# Usage:
#   lessons-effectiveness-audit.sh [--since=quarter]
#
# For every LESSONS.md entry across /opt/*/LESSONS.md, scan git history and
# relevant log files since the entry's date and report one of:
#   - recurred          — evidence the pattern happened again
#   - did-not-recur     — no evidence in the time window
#   - indeterminate     — can't automatically determine (report honestly)
#
# Output: markdown to stdout, one section per LESSONS entry.
#
# Purpose: empirically validate the platform-stewardship claim that problems
# solved once should not recur. If patterns keep recurring, either the rule
# isn't being read or isn't enforceable as written.
set -eE -o pipefail
trap 'echo "ERROR at $LINENO: $BASH_COMMAND (rc=$?)" >&2' ERR

# -----------------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------------
LESSONS_GLOB_PATHS=(
    /opt/site-deploy/LESSONS.md
    /opt/abs-dashboard/LESSONS.md
)
# Additional project LESSONS files discovered dynamically
EXTRA_LESSONS=$(ls /opt/*/LESSONS.md 2>/dev/null | grep -v -E '^(/opt/site-deploy|/opt/abs-dashboard)/LESSONS\.md$' || true)

# Log files that carry evidence of recurrence
HEAVY_COMPUTE_LOG="/var/log/heavy-dev-compute.log"
POST_DEPLOY_LOG="/var/log/post-deploy-rsync.log"
AUTO_DEPLOY_LOG="/var/log/auto-deploy.log"
EVENTS_LOG="/var/log/events.jsonl"
PAID_CALLS_LOG="/var/log/paid-calls.jsonl"

# Scan window default
DEFAULT_SINCE="quarter"

# -----------------------------------------------------------------------------
# ARG PARSING
# -----------------------------------------------------------------------------
since="$DEFAULT_SINCE"
for arg in "$@"; do
    case "$arg" in
        --since=*) since="${arg#--since=}" ;;
        -h|--help)
            echo "usage: lessons-effectiveness-audit.sh [--since=quarter|<N>d]"
            exit 0
            ;;
    esac
done

# Translate "quarter" -> 90 days; Nd -> N days; default 90.
case "$since" in
    quarter) since_days=90 ;;
    *d)      since_days="${since%d}" ;;
    *)       since_days=90 ;;
esac

# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------

# Parse LESSONS.md into records: date|project|title|body
parse_lessons_file() {
    local file="$1"
    local project_name
    # Infer project from path: /opt/<project>/LESSONS.md
    project_name=$(basename "$(dirname "$file")")
    python3 - "$file" "$project_name" <<'PY'
import re, sys, pathlib
path = pathlib.Path(sys.argv[1])
project = sys.argv[2]
text = path.read_text()

# Split on "## YYYY-MM-DD" headings
header_re = re.compile(r'^## \[?(\d{4}-\d{2}-\d{2})\]?[\s—-]*(.*)$', re.MULTILINE)
matches = list(header_re.finditer(text))
for i, m in enumerate(matches):
    date_str = m.group(1)
    title = m.group(2).strip()
    # Skip obvious template / example entries
    if "YYYY-MM-DD" in date_str or "short title" in title.lower():
        continue
    start = m.end()
    end = matches[i+1].start() if i+1 < len(matches) else len(text)
    body = text[start:end].strip()
    # Sanitize newlines and pipes for record format
    body_flat = body.replace("\n", " \\n ").replace("|", "/")
    title_flat = title.replace("|", "/")
    print(f"{date_str}|{project}|{title_flat}|{body_flat}")
PY
}

# Extract search keywords from a LESSONS title. Prefer specific terms (chart
# names, error classes, file paths) over generic words. Returns 0-3 keywords.
extract_keywords() {
    local title="$1"
    python3 - "$title" <<'PY'
import re, sys
title = sys.argv[1].lower()
# Strip leading framing words
for prefix in ("shipped ", "new ", "fixed ", "added ", "ship "):
    if title.startswith(prefix):
        title = title[len(prefix):]
# Tokenize on non-word chars; prefer 5+-char tokens OR hyphenated/underscore compounds
raw = re.findall(r'[a-z0-9_\-./]{3,}', title)
# Reject generic stopwords AND common-english verbs/adjectives that produce noise
stop = set("""the and for with that this from after before under over when then
which what have been has had not but all any one two few was were are when then
because since now also more most some such then into onto without within during
new old big small high low full empty good bad nice cold hot fix fixed bug bugs
ship shipped add added remove removed test tested pass passed fail failed run
ran went made took got set kept left work works worked way ways use used using
via per out off day days week weeks hour hours minute minutes time times
data data. code codes path paths file files line lines call calls page pages
entry entries item items need needs make makes done ended only also same while
well less more much many most least lot lots help helps helped want wants
auto deploy deploys chart charts log logs spec specs test tests case cases""".split())
# Prefer highly-specific tokens: hyphenated/underscore compounds or 7+-char words
def is_specific(t):
    if t in stop: return False
    if '-' in t or '_' in t or '/' in t or '.' in t: return True
    if len(t) >= 7: return True
    return False

keep = [t for t in raw if is_specific(t)]
# De-duplicate while keeping order
seen = set()
out = []
for t in keep:
    if t not in seen:
        seen.add(t)
        out.append(t)
# Keep top 3 specific tokens — less is better for precision
print(" ".join(out[:3]))
PY
}

# Look for recurrence of keyword set in git logs since a given date
scan_git_for_recurrence() {
    local since_date="$1"
    shift
    local keywords="$*"
    local repo_dir hits=0 evidence=""
    # Check both site-deploy (global infra) and project repos
    for repo_dir in /opt/site-deploy /opt/abs-dashboard; do
        [[ ! -d "${repo_dir}/.git" ]] && continue
        for kw in $keywords; do
            local matches
            matches=$(git -C "$repo_dir" log --since="$since_date" --oneline 2>/dev/null \
                      | grep -iE "$kw" | head -2 || true)
            if [[ -n "$matches" ]]; then
                hits=$((hits + 1))
                evidence="${evidence}$(basename "$repo_dir"): ${matches}"$'\n'
            fi
        done
    done
    echo "$hits|$evidence"
}

# Look for recurrence in log files. Requires a line dated AFTER the lesson
# entry — otherwise matching is just historical, not recurrence.
scan_logs_for_recurrence() {
    local since_date="$1"
    shift
    local keywords="$*"
    local hits=0 evidence=""
    for logfile in "$HEAVY_COMPUTE_LOG" "$POST_DEPLOY_LOG" "$AUTO_DEPLOY_LOG"; do
        [[ ! -f "$logfile" ]] && continue
        for kw in $keywords; do
            # Find matching lines and filter by date >= since_date.
            # Pattern extracts ISO date at start OR Unix-style date; if neither,
            # line is ignored (conservatively).
            local matches
            matches=$(awk -v kw="$kw" -v since="$since_date" '
                BEGIN { IGNORECASE = 1 }
                {
                    # Extract YYYY-MM-DD from line, if any
                    if (match($0, /[0-9]{4}-[0-9]{2}-[0-9]{2}/)) {
                        dt = substr($0, RSTART, RLENGTH)
                        if (dt >= since && tolower($0) ~ tolower(kw)) {
                            print dt ": " substr($0, 1, 140)
                        }
                    }
                }
            ' "$logfile" 2>/dev/null | tail -2 || true)
            if [[ -n "$matches" ]]; then
                hits=$((hits + 1))
                evidence="${evidence}$(basename "$logfile"): $(echo "$matches" | head -1)"$'\n'
            fi
        done
    done
    echo "$hits|$evidence"
}

# Verdict logic: combine git + log scans and return status + rationale
verdict_for_entry() {
    local entry_date="$1"
    local title="$2"

    local keywords
    keywords=$(extract_keywords "$title")
    if [[ -z "$keywords" ]]; then
        echo "indeterminate|no specific keywords extractable from title"
        return
    fi

    # Only look at commits AFTER the lesson was written
    local since_arg="${entry_date}"
    local git_result log_result git_hits git_evidence log_hits log_evidence
    git_result=$(scan_git_for_recurrence "$since_arg" $keywords)
    git_hits="${git_result%%|*}"
    git_evidence="${git_result#*|}"
    log_result=$(scan_logs_for_recurrence "$since_arg" $keywords)
    log_hits="${log_result%%|*}"
    log_evidence="${log_result#*|}"

    local total_hits=$((git_hits + log_hits))
    if [[ "$total_hits" -eq 0 ]]; then
        echo "did-not-recur|no matches for keywords '${keywords}' in git/logs since ${entry_date}"
    elif [[ "$total_hits" -ge 2 ]]; then
        local combined="${git_evidence}${log_evidence}"
        # Compact multi-line evidence into one backtick-safe line
        local evidence_brief
        evidence_brief=$(echo "$combined" | head -3 | tr '\n' ';' | sed 's/;$//')
        echo "recurred|evidence: ${evidence_brief}"
    else
        # 1 hit is ambiguous: could be a follow-up commit referencing the fix
        local combined="${git_evidence}${log_evidence}"
        local evidence_brief
        evidence_brief=$(echo "$combined" | head -2 | tr '\n' ';' | sed 's/;$//')
        echo "indeterminate|1 keyword match — could be follow-up reference or a true recurrence: ${evidence_brief}"
    fi
}

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

echo "# LESSONS Effectiveness Audit"
echo ""
echo "_Window: last ${since_days} days. Scanned git history (site-deploy + abs-dashboard) and relevant logs._"
echo ""
echo "Purpose: check whether patterns documented in LESSONS.md recurred after the entry was written. If yes, the preventive rule didn't stick — either agents aren't reading it or it's not enforceable as written."
echo ""

# Collect all entries across all LESSONS files
all_entries=$(mktemp)
trap 'rm -f "$all_entries"' EXIT

for lf in "${LESSONS_GLOB_PATHS[@]}" $EXTRA_LESSONS; do
    [[ ! -f "$lf" ]] && continue
    parse_lessons_file "$lf" >> "$all_entries"
done

entry_count=$(wc -l < "$all_entries")
if [[ "$entry_count" -eq 0 ]]; then
    echo "No LESSONS entries found. Nothing to audit."
    exit 0
fi

# Stats
recurred_count=0
clean_count=0
indeterminate_count=0

# Render: newest first
sort -r "$all_entries" | while IFS='|' read -r entry_date project title body; do
    [[ -z "$entry_date" ]] && continue

    verdict=$(verdict_for_entry "$entry_date" "$title")
    status="${verdict%%|*}"
    rationale="${verdict#*|}"

    # Emoji-free status marker
    case "$status" in
        recurred)         marker="[RECURRED]" ;;
        did-not-recur)    marker="[CLEAN]" ;;
        indeterminate)    marker="[INDETERMINATE]" ;;
        *)                marker="[?]" ;;
    esac

    echo "## ${marker} ${entry_date} — ${title}"
    echo ""
    echo "**Project:** ${project}"
    echo ""
    echo "**Verdict:** ${status}"
    echo ""
    echo "**Rationale:** ${rationale}"
    echo ""
    echo "---"
    echo ""
done

# Summary footer (count again — subshell state doesn't escape the while loop)
total=$(wc -l < "$all_entries")
echo ""
echo "## Summary"
echo ""
echo "Audited **${total}** LESSONS entries across $(ls /opt/*/LESSONS.md 2>/dev/null | wc -l) project files."
echo ""
echo "Read the sections above for per-entry status. Any **[RECURRED]** entry is a signal the preventive rule didn't hold — those are the highest-value targets for rule-tightening or enforcement automation."
echo ""
echo "**Note on indeterminate verdicts:** the scanner uses keyword matching against git log and log files. A one-hit match often means a follow-up commit referenced the original fix, not a true recurrence — human eyes needed."
