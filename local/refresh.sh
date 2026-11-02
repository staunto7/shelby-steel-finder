#!/bin/bash
# Mac background refresh for the sources that block GitHub's servers (USSSA, NSA).
# launchd runs this every 15 minutes while the Mac is awake (see local/com.shelbysteel.refresh.plist).
#   - Full refresh (listings, team lists, ballparks, pool play) when the last one is 6+ hours old (four times a day).
#   - Otherwise, Thursday through Monday morning, just pool play and brackets for Shelby Steel tournaments.
# Pushes to GitHub only when something changed; GitHub then republishes the site. Uses no Claude usage.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3
STAMP="$HOME/Library/Application Support/shelby-steel-finder/last-full"
LOCK="${TMPDIR:-/tmp}/shelby-steel-refresh.lock"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$(dirname "$PY")"
export GIT_SSH_COMMAND="ssh -o BatchMode=yes"

mkdir "$LOCK" 2>/dev/null || { echo "$(date '+%F %T') already running"; exit 0; }
trap 'rmdir "$LOCK"' EXIT
mkdir -p "$(dirname "$STAMP")"
cd "$REPO" || exit 1

now=$(date +%s)
last=$(cat "$STAMP" 2>/dev/null || echo 0)
dow=$(date +%u)   # 1 = Monday ... 7 = Sunday
hour=$(date +%H)

if (( now - last >= 6 * 3600 )); then
  mode=full
elif (( dow >= 4 )) || { (( dow == 1 )) && (( 10#$hour < 6 )); }; then
  mode=games
else
  exit 0
fi

echo "$(date '+%F %T') $mode refresh"
git pull -q --rebase -X theirs origin main || { echo "pull failed"; exit 1; }

if [[ $mode == full ]]; then
  "$PY" fetch.py && "$PY" teams.py && "$PY" games.py && echo "$now" > "$STAMP"
  git add site/ cache/
else
  "$PY" games.py
  git add site/games/
fi

if git diff --cached --quiet; then
  echo "no changes"
  exit 0
fi
git commit -q -m "Mac refresh ($mode): USSSA and NSA" && \
  { git push -q origin main || { git pull -q --rebase -X theirs origin main && git push -q origin main; }; } && \
  echo "pushed"
