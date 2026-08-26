#!/usr/bin/env python3
"""
Publish gate: does this MP3 contain as much audio as the script implies?

scan_static.py catches noise. This catches the opposite failure — an episode
that rendered "successfully" but is mostly silence because generation crashed
and synth_chunk substituted 0.4s gaps. That is what shipped episodes 015-035.

Usage:  check_duration.py scripts/ep015.json audio-work/out/ep015.mp3
Exit 0 = plausible, exit 1 = too short, do not publish.

It reuses the renderer's own model of how long speech takes
(CHARS_PER_SEC = 15) plus the script's declared pauses, so it needs no
tuning per episode and no extra dependencies beyond ffprobe.
"""
import json
import subprocess
import sys

CHARS_PER_SEC = 15.0     # must match tools/render_episode.py
MIN_RATIO = 0.75         # ship nothing below 75% of the expected length
MAX_RATIO = 1.60         # far too long = a runaway looping take


def split_sentences(text):
    import re
    return [p for p in re.split(r"(?<=[.!?…])\s+", text.strip()) if p]


def expected_seconds(script):
    """Speech time + the pauses the renderer inserts between them."""
    total = 0.0
    for seg in script["segments"]:
        isp = seg.get("inter_sentence_pause_s", 0.5)
        itp = seg.get("inter_turn_pause_s", 0.8)
        turns = seg["turns"]
        for turn in turns:
            if "pause" in turn:
                # matches render_episode.py: a pause turn contributes only its
                # own length, with no inter_turn_pause_s added after it.
                total += turn["pause"]
                continue
            text = turn["text"]
            total += len(text) / CHARS_PER_SEC
            # renderer adds isp between chunks; when isp >= 0.5 a chunk is one
            # sentence, otherwise sentences are grouped into ~140-char chunks.
            sents = split_sentences(text)
            n_chunks = len(sents) if isp >= 0.5 else max(1, (len(text) // 140) + 1)
            total += isp * max(0, n_chunks - 1)
            total += itp
    return total


def actual_seconds(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def mean_volume_db(path):
    """Second, independent check: an all-silence file has a floor near -91 dB."""
    r = subprocess.run(["ffmpeg", "-i", path, "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    return None


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    script_path, mp3 = sys.argv[1], sys.argv[2]
    with open(script_path) as f:
        script = json.load(f)

    exp = expected_seconds(script)
    act = actual_seconds(mp3)
    ratio = act / exp if exp else 0.0
    vol = mean_volume_db(mp3)

    print(f"[duration] expected ~{exp/60:.1f} min, got {act/60:.1f} min "
          f"({ratio*100:.0f}%), mean volume {vol} dB")

    ok = True
    if ratio < MIN_RATIO:
        print(f"[duration] FAIL — only {ratio*100:.0f}% of expected length. "
              f"Generation almost certainly failed and was replaced by silence.")
        ok = False
    if ratio > MAX_RATIO:
        print(f"[duration] FAIL — {ratio*100:.0f}% of expected length. "
              f"Looks like a runaway looping take.")
        ok = False
    if vol is not None and vol < -50:
        print(f"[duration] FAIL — mean volume {vol} dB is effectively silence.")
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
