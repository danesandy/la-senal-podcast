#!/usr/bin/env python3
"""Build ~12s voice-clone reference WAVs by concatenating clean clips per speaker.

Picks the longest clips (more prosody), inserts 0.3s gaps, peak-normalizes.
Usage: python3 build_refs.py            # builds refs for all speakers found
"""
import os
import subprocess
import glob
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(PROJ, "voices", "raw")
BANK = os.path.join(PROJ, "voices", "bank")
TARGET_S = 12.0

os.makedirs(BANK, exist_ok=True)


def duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def build_ref(speaker, files, out_path):
    durs = sorted(((duration(f), f) for f in files), reverse=True)
    picked, total = [], 0.0
    for d, f in durs:
        if d < 2.0 or d > 10.0:
            continue
        picked.append(f)
        total += d
        if total >= TARGET_S:
            break
    if not picked:
        print(f"  {speaker}: no usable clips!", file=sys.stderr)
        return False
    inputs = []
    filters = []
    for i, f in enumerate(picked):
        inputs += ["-i", f]
        filters.append(f"[{i}:a]")
    fc = "".join(filters) + f"concat=n={len(picked)}:v=0:a=1[cat];[cat]loudnorm=I=-20:TP=-2[out]"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *inputs,
         "-filter_complex", fc, "-map", "[out]", "-ar", "24000", "-ac", "1", out_path],
        check=True)
    print(f"  {speaker}: {len(picked)} clips, {total:.1f}s -> {out_path}")
    return True


def main():
    speakers = {}
    for corpus in os.listdir(RAW):
        cdir = os.path.join(RAW, corpus)
        if not os.path.isdir(cdir):
            continue
        for wav in glob.glob(os.path.join(cdir, "*.wav")):
            spk = os.path.basename(wav).rsplit("_", 1)[0]
            speakers.setdefault(spk, []).append(wav)
    for spk, files in sorted(speakers.items()):
        out = os.path.join(BANK, f"{spk}.wav")
        if not os.path.exists(out):
            build_ref(spk, files, out)
    print("refs built:", len(glob.glob(os.path.join(BANK, "*.wav"))))


if __name__ == "__main__":
    main()
