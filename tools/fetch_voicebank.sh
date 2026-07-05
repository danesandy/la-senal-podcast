#!/bin/bash
# Build voice bank source clips from OpenSLR 72 (Colombian) + 75 (Venezuelan).
# Disk-frugal: one zip at a time, extract top speakers' clips, delete zip.
set -euo pipefail

PROJ="/Users/danesandy/la-senal-podcast"
RAW="$PROJ/voices/raw"
TMP="${TMPDIR:-/tmp}/slr_dl"
mkdir -p "$RAW" "$TMP"

fetch_corpus() {
  local slr_id="$1" zip_name="$2" tag="$3"
  local url="https://www.openslr.org/resources/${slr_id}/${zip_name}"
  local tsv="line_index_${zip_name##*_}"       # e.g. line_index_female.zip -> wrong; fix below
  echo "=== $tag ($zip_name) ==="
  curl -sSL -o "$TMP/$zip_name" "$url"
  # List contents, group by speaker id (filename prefix before last underscore-number block)
  unzip -l "$TMP/$zip_name" | awk '{print $4}' | grep '\.wav$' > "$TMP/${tag}_files.txt" || true
  # Speaker id = field like es_co_12345 in "es_co_12345_01234567890.wav"
  awk -F/ '{print $NF}' "$TMP/${tag}_files.txt" \
    | sed -E 's/_[0-9]+\.wav$//' | sort | uniq -c | sort -rn | head -5 > "$TMP/${tag}_speakers.txt"
  echo "top speakers:"; cat "$TMP/${tag}_speakers.txt"
  # Extract up to 25 clips for each of the top 3 speakers
  mkdir -p "$RAW/$tag"
  local n=0
  while read -r count spk; do
    n=$((n+1)); [ $n -gt 3 ] && break
    grep "$spk" "$TMP/${tag}_files.txt" | head -25 > "$TMP/${tag}_${spk}_pick.txt"
    ( cd "$RAW/$tag" && unzip -o -j -q "$TMP/$zip_name" $(cat "$TMP/${tag}_${spk}_pick.txt" | tr '\n' ' ') ) || true
  done < "$TMP/${tag}_speakers.txt"
  rm -f "$TMP/$zip_name"
  echo "extracted $(ls "$RAW/$tag" | wc -l | tr -d ' ') clips for $tag; zip deleted"
}

# Also grab the line-index TSVs (transcripts) for reference-clip selection
curl -sSL -o "$RAW/line_index_co_female.tsv" "https://www.openslr.org/resources/72/line_index_female.tsv" || true
curl -sSL -o "$RAW/line_index_co_male.tsv"   "https://www.openslr.org/resources/72/line_index_male.tsv" || true
curl -sSL -o "$RAW/line_index_ve_female.tsv" "https://www.openslr.org/resources/75/line_index_female.tsv" || true
curl -sSL -o "$RAW/line_index_ve_male.tsv"   "https://www.openslr.org/resources/75/line_index_male.tsv" || true

fetch_corpus 72 es_co_female.zip co_female
fetch_corpus 72 es_co_male.zip   co_male
fetch_corpus 75 es_ve_female.zip ve_female
fetch_corpus 75 es_ve_male.zip   ve_male

df -h /System/Volumes/Data | tail -1
echo "VOICEBANK_FETCH_DONE"
