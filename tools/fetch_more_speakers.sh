#!/bin/bash
# Supplemental fetch: speakers ranked 4-6 from the Colombian corpora.
set -euo pipefail
PROJ="/Users/danesandy/la-senal-podcast"
RAW="$PROJ/voices/raw"
TMP="${TMPDIR:-/tmp}/slr_dl"
mkdir -p "$TMP"

fetch_ranked() {
  local slr_id="$1" zip_name="$2" tag="$3" from_rank="$4" to_rank="$5"
  local url="https://www.openslr.org/resources/${slr_id}/${zip_name}"
  echo "=== $tag ranks $from_rank-$to_rank ==="
  curl -sSL -o "$TMP/$zip_name" "$url"
  unzip -l "$TMP/$zip_name" | awk '{print $4}' | grep '\.wav$' > "$TMP/${tag}_files.txt"
  awk -F/ '{print $NF}' "$TMP/${tag}_files.txt" \
    | sed -E 's/_[0-9]+\.wav$//' | sort | uniq -c | sort -rn \
    | sed -n "${from_rank},${to_rank}p" > "$TMP/${tag}_speakers.txt"
  cat "$TMP/${tag}_speakers.txt"
  mkdir -p "$RAW/$tag"
  while read -r count spk; do
    grep "$spk" "$TMP/${tag}_files.txt" | head -25 > "$TMP/${tag}_${spk}_pick.txt"
    ( cd "$RAW/$tag" && unzip -o -j -q "$TMP/$zip_name" $(cat "$TMP/${tag}_${spk}_pick.txt" | tr '\n' ' ') ) || true
  done < "$TMP/${tag}_speakers.txt"
  rm -f "$TMP/$zip_name"
}

fetch_ranked 72 es_co_male.zip   co_male   4 6
fetch_ranked 72 es_co_female.zip co_female 4 5
echo "MORE_SPEAKERS_DONE"
