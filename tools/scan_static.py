#!/usr/bin/env python3
"""Static/artifact scanner. Exits 0 if an MP3 is clean, 1 if static is found.
Windowed crest-factor gate on loud regions — a coarse safety net used as a
publish gate (the render's per-chunk Whisper QC is the primary defense).
Usage: python3 scan_static.py <file.mp3>"""
import sys
import subprocess
import numpy as np

path = sys.argv[1]
raw = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", path, "-ar", "16000", "-ac", "1", "-f", "f32le", "-"],
    capture_output=True).stdout
x = np.frombuffer(raw, dtype=np.float32)
sr = 16000
win = sr // 2  # 0.5s
n = len(x) // win
flags = []
for i in range(n):
    w = x[i * win:(i + 1) * win]
    rms = float(np.sqrt(np.mean(w ** 2))) + 1e-9
    peak = float(np.max(np.abs(w))) + 1e-9
    if rms > 0.02 and peak / rms < 3.2:
        flags.append(i * 0.5)
dur = len(x) / sr
if flags:
    print(f"STATIC: {len(flags)} suspect windows ({len(flags)*0.5:.0f}s of {dur:.0f}s); "
          f"first at {flags[0]:.0f}s")
    sys.exit(1)
print(f"CLEAN: {dur:.0f}s, no static")
sys.exit(0)
