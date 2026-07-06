#!/usr/bin/env python3
"""Static/artifact scanner. Exits 0 if an MP3 is clean, 1 if sustained static
is found. Used as the publish gate (the render's per-chunk QC is the primary
defense).

Real Chatterbox artifacts (looping drones / noise) are SUSTAINED — many
contiguous low-crest windows. Natural speech occasionally produces a single
loud window (a fricative, an emphatic syllable) that dips below the crest
threshold; those isolated blips are not static. So we flag only a contiguous
RUN of low-crest windows (>= MIN_RUN), never isolated ones.

Usage: python3 scan_static.py <file.mp3>
"""
import sys
import subprocess
import numpy as np

MIN_RUN = 5          # contiguous 0.5s windows (=2.5s) of low crest = real static
CREST_MIN = 3.2
RMS_GATE = 0.02

path = sys.argv[1]
raw = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", path, "-ar", "16000", "-ac", "1", "-f", "f32le", "-"],
    capture_output=True).stdout
x = np.frombuffer(raw, dtype=np.float32)
sr = 16000
win = sr // 2  # 0.5s
n = len(x) // win

flagged = []
for i in range(n):
    w = x[i * win:(i + 1) * win]
    rms = float(np.sqrt(np.mean(w ** 2))) + 1e-9
    peak = float(np.max(np.abs(w))) + 1e-9
    flagged.append(rms > RMS_GATE and peak / rms < CREST_MIN)

# longest contiguous run of flagged windows
longest = cur = 0
run_start = best_start = 0
for i, f in enumerate(flagged):
    if f:
        if cur == 0:
            run_start = i
        cur += 1
        if cur > longest:
            longest, best_start = cur, run_start
    else:
        cur = 0

dur = len(x) / sr
total = sum(flagged)
if longest >= MIN_RUN:
    print(f"STATIC: sustained run of {longest} windows ({longest*0.5:.1f}s) "
          f"starting at {best_start*0.5:.0f}s; {total} flagged total of {dur:.0f}s")
    sys.exit(1)
print(f"CLEAN: {dur:.0f}s (longest low-crest run {longest*0.5:.1f}s, "
      f"{total} isolated windows — within normal speech)")
sys.exit(0)
