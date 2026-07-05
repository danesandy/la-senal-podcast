#!/bin/bash
# Queue runner: render + publish every script that isn't yet in episodes.json.
# Safe to run any time; processes episodes in order; resumes partial renders.
# Used by the nightly launchd job and for manual catch-up runs.
set -uo pipefail

export PROJ="$(cd "$(dirname "$0")/.." && pwd)"
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/audio-work/produce.log"
mkdir -p "$PROJ/audio-work"

# Single-instance lock
LOCKDIR="$PROJ/audio-work/.produce.lock"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "another produce.sh is running; exiting" | tee -a "$LOG"
  exit 0
fi
trap 'rmdir "$LOCKDIR"' EXIT

published_ids=$(python3 -c "
import json
with open('$PROJ/episodes.json') as f:
    print(' '.join(e['id'] for e in json.load(f)['episodes']))
")

for script in "$PROJ/scripts"/ep*.json; do
  ep=$(basename "$script" .json | sed 's/^ep//')
  if [[ " $published_ids " == *" $ep "* ]]; then
    continue
  fi
  echo "[produce $(date '+%F %T')] rendering ep$ep" | tee -a "$LOG"
  if caffeinate -i "$PY" "$PROJ/tools/render_episode.py" "$script" >> "$LOG" 2>&1; then
    echo "[produce $(date '+%F %T')] publishing ep$ep" | tee -a "$LOG"
    "$PROJ/tools/publish.sh" "$ep" >> "$LOG" 2>&1 || {
      echo "[produce] PUBLISH FAILED ep$ep" | tee -a "$LOG"; exit 1; }
  else
    echo "[produce] RENDER FAILED ep$ep" | tee -a "$LOG"; exit 1
  fi
done
echo "[produce $(date '+%F %T')] queue empty / done" | tee -a "$LOG"
