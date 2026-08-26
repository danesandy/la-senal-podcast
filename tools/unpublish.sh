#!/bin/bash
# Pull a range of episodes back out of the feed and delete their GitHub Releases.
#
#   bash tools/unpublish.sh 015 035          # remove 015..035
#   DRY=1 bash tools/unpublish.sh 015 035    # show what would happen
#
# After this, produce.sh sees those episodes as pending again and will
# re-render them — so only run it once the render bug is actually fixed,
# or with the launchd job stopped.
set -uo pipefail
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
REPO="danesandy/la-senal-podcast"
FROM="$1"; TO="$2"
cd "$PROJ" || exit 1

ids=$(python3 -c "print(' '.join(f'{i:03d}' for i in range(int('$FROM'), int('$TO')+1)))")
echo "Episodes to unpublish: $ids"
[ "${DRY:-0}" = "1" ] && { echo "(dry run)"; exit 0; }

read -r -p "This removes them from the feed and deletes their releases. Type YES: " ok
[ "$ok" = "YES" ] || { echo "aborted"; exit 1; }

# 1. Drop from the manifest and regenerate the feed.
python3 - "$ids" <<'PY'
import json, sys, os
ids = set(sys.argv[1].split())
p = "episodes.json"
m = json.load(open(p))
before = len(m["episodes"])
m["episodes"] = [e for e in m["episodes"] if e["id"] not in ids]
json.dump(m, open(p, "w"), indent=2, ensure_ascii=False)
print(f"episodes.json: {before} -> {len(m['episodes'])}")
PY
python3 tools/gen_feed.py

# 2. Delete the releases so nothing can still fetch the silent audio.
for id in $ids; do
  if gh release view "ep-$id" -R "$REPO" >/dev/null 2>&1; then
    gh release delete "ep-$id" -R "$REPO" -y --cleanup-tag 2>/dev/null \
      || gh release delete "ep-$id" -R "$REPO" -y
    echo "deleted release ep-$id"
  fi
done

# 3. Clear any cached working audio for those episodes.
for id in $ids; do rm -rf "audio-work/ep$id" "audio-work/out/ep$id.mp3"; done

git add episodes.json feed.xml
git commit -q -m "unpublish episodes $FROM-$TO (silent render)" && git push -q
echo
echo "Done. Feed now lists $(python3 -c "import json;print(len(json.load(open('episodes.json'))['episodes']))") episodes."
echo "Apple Podcasts will drop them within a few hours; pull to refresh to hurry it."
