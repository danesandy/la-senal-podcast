#!/bin/bash
# Publish one rendered episode: upload MP3 to a GitHub Release, update
# episodes.json + feed.xml, push, and delete the local MP3 (disk is tight).
# Usage: publish.sh <ep_id>   (e.g. publish.sh 000)
set -euo pipefail

export PROJ="$(cd "$(dirname "$0")/.." && pwd)"
EP="$1"
MP3="$PROJ/audio-work/out/ep${EP}.mp3"
REPO="danesandy/la-senal-podcast"
TAG="ep-${EP}"

[ -f "$MP3" ] || { echo "missing $MP3"; exit 1; }

BYTES=$(stat -f%z "$MP3")
DUR=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$MP3")

# Create release (idempotent) and upload asset
gh release view "$TAG" -R "$REPO" >/dev/null 2>&1 || \
  gh release create "$TAG" -R "$REPO" --title "Episodio $EP" --notes "Audio asset for episode $EP" >/dev/null
gh release upload "$TAG" "$MP3" -R "$REPO" --clobber

URL="https://github.com/${REPO}/releases/download/${TAG}/ep${EP}.mp3"

# Update manifest entry (jq merge)
python3 - "$EP" "$URL" "$BYTES" "$DUR" <<'EOF'
import json, sys, os
from datetime import datetime, timezone
ep_id, url, size, dur = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
manifest_path = os.path.join(os.environ["PROJ"], "episodes.json")
scripts_path = os.path.join(os.environ["PROJ"], "scripts", f"ep{ep_id}.json")
with open(manifest_path) as f:
    m = json.load(f)
with open(scripts_path) as f:
    s = json.load(f)
m["episodes"] = [e for e in m["episodes"] if e["id"] != ep_id]
m["episodes"].append({
    "id": ep_id,
    "title": s["title"],
    "description": s.get("description", ""),
    "pubDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    "duration_s": dur,
    "bytes": size,
    "url": url,
})
with open(manifest_path, "w") as f:
    json.dump(m, f, indent=2, ensure_ascii=False)
print(f"manifest updated: ep{ep_id}")
EOF

python3 "$PROJ/tools/gen_feed.py"

cd "$PROJ"
git add episodes.json feed.xml transcripts vocab-logs
git commit -q -m "publish: episode ${EP}" || true
git push -q origin main

rm -f "$MP3"
echo "PUBLISHED ep${EP} -> $URL"
