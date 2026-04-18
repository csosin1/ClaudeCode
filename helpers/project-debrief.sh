#!/bin/bash
# project-debrief.sh — four-section plain-English narrative debrief for a project.
#
# Usage:
#   project-debrief.sh <project-name> [--since=<N>d]
#
# Produces a four-section markdown narrative on stdout:
#   1. What worked        — commits/features that shipped cleanly
#   2. What stumbled      — LESSONS entries, retries, multi-iteration fixes
#   3. What cost          — concrete token spend (proxy for effort) from tokens.json
#   4. What's worth watching — specific observations with signal, not noise
#
# Designed for a non-technical reader: no SHAs in narrative, concrete dollar
# figures, reads like an engineer's weekly update.
set -eE -o pipefail
trap 'echo "ERROR at $LINENO: $BASH_COMMAND (rc=$?)" >&2' ERR

# -----------------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------------
TOKENS_JSON="/var/www/landing/tokens.json"
OPT_ROOT="/opt"
DEFAULT_SINCE="7d"
USER_ACTION_BIN="/usr/local/bin/user-action.sh"

# -----------------------------------------------------------------------------
# ARG PARSING
# -----------------------------------------------------------------------------
project="${1:-}"
since="$DEFAULT_SINCE"
for arg in "$@"; do
    case "$arg" in
        --since=*) since="${arg#--since=}" ;;
    esac
done

if [[ -z "$project" || "$project" == --* ]]; then
    echo "usage: project-debrief.sh <project-name> [--since=7d]" >&2
    exit 2
fi

project_dir="${OPT_ROOT}/${project}"
if [[ ! -d "$project_dir" ]]; then
    echo "project directory not found: $project_dir" >&2
    exit 3
fi

# Git "since" needs a format it understands. "7d" -> "7 days ago".
case "$since" in
    *d) git_since="${since%d} days ago" ;;
    *w) git_since="${since%w} weeks ago" ;;
    *)  git_since="$since" ;;
esac

# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------

# Pull spend for a project from tokens.json. tokens.json keys chats by chat-id,
# not project. Resolve by matching cwd_slug to the project dir.
get_project_spend_json() {
    python3 - "$project" "$TOKENS_JSON" <<'PY'
import json, sys, pathlib
project = sys.argv[1]
path = pathlib.Path(sys.argv[2])
if not path.exists():
    print("{}")
    sys.exit(0)
try:
    data = json.loads(path.read_text())
except json.JSONDecodeError:
    print("{}")
    sys.exit(0)

# cwd_slug is the cwd with slashes replaced by dashes; match on trailing project name
matches = []
for chat_id, rec in data.get("chats", {}).items():
    slug = rec.get("cwd_slug", "") or ""
    # Match when slug is exactly opt-<project>, ends in -<project>, or contains project token
    if (slug == f"opt-{project}"
            or slug.endswith(f"-{project}")
            or slug.startswith(f"opt-{project}-")
            or chat_id == project):
        matches.append((chat_id, rec))

result = {"chats": matches, "updated_at": data.get("updated_at")}
print(json.dumps(result))
PY
}

# Count commits and return top-line activity summary for the project.
get_commit_activity() {
    if [[ ! -d "${project_dir}/.git" ]]; then
        echo "not-a-git-repo"
        return
    fi
    local total
    total=$(git -C "$project_dir" log --since="$git_since" --oneline 2>/dev/null | wc -l)
    echo "$total"
}

# Return commit subjects since `git_since` as a newline-separated list.
get_commit_subjects() {
    if [[ ! -d "${project_dir}/.git" ]]; then
        return
    fi
    git -C "$project_dir" log --since="$git_since" --pretty=format:'%s' 2>/dev/null || true
}

# Pull LESSONS entries dated within the window.
get_recent_lessons() {
    local lessons_file="${project_dir}/LESSONS.md"
    [[ ! -f "$lessons_file" ]] && return
    # Grep entries starting with "## YYYY-MM-DD". Filter by date threshold.
    local cutoff_epoch
    cutoff_epoch=$(date -d "$git_since" +%s 2>/dev/null || echo 0)
    python3 - "$lessons_file" "$cutoff_epoch" <<'PY'
import re, sys, datetime, pathlib
path = pathlib.Path(sys.argv[1])
cutoff = int(sys.argv[2])
text = path.read_text()
# Match "## YYYY-MM-DD" possibly followed by " — " or " " + title
pattern = re.compile(r'^## \[?(\d{4}-\d{2}-\d{2})\]?[\s—-]*(.*)$', re.MULTILINE)
for m in pattern.finditer(text):
    date_str, title = m.group(1), m.group(2).strip()
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        if dt.timestamp() >= cutoff:
            print(f"{date_str}|{title}")
    except ValueError:
        continue
PY
}

# Tail of CHANGES.md — the project chat's own summary of recent work.
get_recent_changes() {
    local changes_file="${project_dir}/CHANGES.md"
    [[ ! -f "$changes_file" ]] && return
    # Take the most recent ~60 lines as a heuristic window of "recent activity"
    tail -n 60 "$changes_file"
}

# Open user-actions filtered by project.
get_open_user_actions() {
    [[ ! -x "$USER_ACTION_BIN" ]] && return
    "$USER_ACTION_BIN" list 2>/dev/null | grep -E "^\[ua-.* ${project} " | head -10 || true
}

# -----------------------------------------------------------------------------
# RENDER
# -----------------------------------------------------------------------------

commit_count=$(get_commit_activity)
commit_subjects=$(get_commit_subjects)
lessons_entries=$(get_recent_lessons)
recent_changes=$(get_recent_changes)
open_actions=$(get_open_user_actions)
spend_json=$(get_project_spend_json)

# Pull top-line cost figure and most-expensive chat. One Python pass over the
# JSON to avoid duplicating parse logic and to sidestep heredoc+stdin conflicts.
spend_summary=$(python3 -c "
import json
d = json.loads('''$spend_json''')
chats = d.get('chats', [])
total = sum(c[1]['tokens'].get('last_7d', {}).get('cost', 0) for c in chats)
if not chats:
    print(f'{total:.2f}|none|0')
else:
    best = max(chats, key=lambda c: c[1]['tokens'].get('last_7d', {}).get('cost', 0))
    cost = best[1]['tokens'].get('last_7d', {}).get('cost', 0)
    print(f'{total:.2f}|{best[0]}|{cost:.2f}')
")
total_cost="${spend_summary%%|*}"
rest="${spend_summary#*|}"
top_chat_id="${rest%|*}"
top_chat_cost="${rest#*|}"
cost_per_commit="n/a"
if [[ "$commit_count" =~ ^[0-9]+$ && "$commit_count" -gt 0 ]]; then
    cost_per_commit=$(python3 -c "print(f'{${total_cost}/${commit_count}:.0f}')")
fi

# -----------------------------------------------------------------------------
# OUTPUT
# -----------------------------------------------------------------------------

cat <<EOF
# Debrief: ${project} (last ${since})

EOF

# ---- Section 1: What worked ----
echo "## What worked"
echo ""
if [[ "$commit_count" == "not-a-git-repo" ]]; then
    echo "No git history available for this project — can't summarize shipped work."
elif [[ "$commit_count" -eq 0 ]]; then
    echo "No commits landed in the window. Either the project paused, or work was"
    echo "happening in worktrees that hadn't merged yet."
else
    # Extract non-fix, non-revert commits — the "worked" subset.
    clean_commits=$(echo "$commit_subjects" | grep -viE '^(fix|revert|retry|hotfix|wip)' | head -6 || true)
    echo "${commit_count} commits landed over the window."
    if [[ -n "$clean_commits" ]]; then
        echo ""
        echo "Headline work that shipped cleanly:"
        echo "$clean_commits" | sed 's/^/- /'
    fi
fi
echo ""

# ---- Section 2: What stumbled ----
echo "## What stumbled"
echo ""
stumble_commits=$(echo "$commit_subjects" | grep -iE '^(fix|revert|retry|hotfix)' | head -6 || true)
if [[ -n "$lessons_entries" ]]; then
    echo "LESSONS entries written in the window — each means a problem surfaced"
    echo "that wasn't obvious from the code, and a preventive rule now exists:"
    echo ""
    while IFS='|' read -r dt title; do
        [[ -z "$dt" ]] && continue
        echo "- **${dt}** — ${title}"
    done <<< "$lessons_entries"
    echo ""
fi
if [[ -n "$stumble_commits" ]]; then
    echo "Fix / retry / revert commits in the window:"
    echo "$stumble_commits" | sed 's/^/- /'
    echo ""
fi
if [[ -z "$lessons_entries" && -z "$stumble_commits" ]]; then
    echo "Nothing notable surfaced. Either the window was quiet or problems were"
    echo "resolved without leaving an LESSONS entry — the latter is worth a look."
    echo ""
fi

# ---- Section 3: What cost ----
echo "## What cost"
echo ""
if [[ "$total_cost" == "0.00" || -z "$total_cost" ]]; then
    echo "No recorded spend against this project in tokens.json over the window."
else
    echo "Total project spend (last 7 days, all matching chats): **\$${total_cost}**."
    if [[ "$top_chat_id" != "none" && "$top_chat_cost" != "0.00" ]]; then
        echo ""
        echo "Most expensive single chat: **${top_chat_id}** at \$${top_chat_cost}."
    fi
    if [[ "$cost_per_commit" != "n/a" ]]; then
        echo ""
        echo "Cost per commit across the window: ~\$${cost_per_commit}."
    fi
fi
echo ""

# ---- Section 4: What's worth watching ----
echo "## What's worth watching"
echo ""

wrote_something=0

if [[ -n "$open_actions" ]]; then
    action_count=$(echo "$open_actions" | wc -l)
    echo "- ${action_count} open user-actions on this project. If any are gating deploys"
    echo "  or paid-API access, they're a silent brake."
    wrote_something=1
fi

if [[ -n "$lessons_entries" ]]; then
    lesson_count=$(echo "$lessons_entries" | wc -l)
    if [[ "$lesson_count" -ge 3 ]]; then
        echo "- ${lesson_count} LESSONS entries in one window is high. Worth checking"
        echo "  whether the root causes cluster — a cluster suggests a systemic fix"
        echo "  beats per-incident rules."
        wrote_something=1
    fi
fi

if [[ "$commit_count" =~ ^[0-9]+$ && "$commit_count" -gt 0 ]]; then
    # Count fix/revert ratio.
    fix_count=$(echo "$commit_subjects" | grep -icE '^(fix|revert|hotfix)' || true)
    if [[ "$fix_count" -gt 0 ]]; then
        ratio=$(python3 -c "print(f'{100*${fix_count}/${commit_count}:.0f}')")
        if [[ "$ratio" -ge 40 ]]; then
            echo "- ${ratio}% of commits were fixes / reverts / hotfixes. High rework"
            echo "  ratio — suggests specs arriving under-cooked or tests missing coverage."
            wrote_something=1
        fi
    fi
fi

if [[ "$total_cost" != "0.00" && -n "$total_cost" ]]; then
    cost_int=${total_cost%.*}
    if [[ "$cost_int" -ge 1500 ]]; then
        echo "- Spend over \$1500 in one week on a single project is the top-tier band."
        echo "  Worth checking whether the work was load-bearing or exploratory."
        wrote_something=1
    fi
fi

if [[ "$wrote_something" -eq 0 ]]; then
    echo "No anomalies flagged by this pass. Absence of signal isn't absence of"
    echo "problem — a human read of recent CHANGES.md is still worth the 2 minutes."
fi
echo ""
