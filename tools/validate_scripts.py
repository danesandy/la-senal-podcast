#!/usr/bin/env python3
"""Validate all episode scripts: parse, schema, voices, word budgets."""
import json
import os
import sys
import glob

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(PROJ, "voices", "voicebank.json")) as f:
    VOICES = set(json.load(f)["voices"].keys())

with open(os.path.join(PROJ, "curriculum", "level-map.json")) as f:
    STAGES = {s["id"]: s for s in json.load(f)["stages"]}

failures = 0
for path in sorted(glob.glob(os.path.join(PROJ, "scripts", "ep*.json"))):
    name = os.path.basename(path)
    problems = []
    try:
        ep = json.load(open(path))
    except Exception as e:
        print(f"FAIL {name}: JSON parse error: {e}")
        failures += 1
        continue
    for field in ("episode", "day", "title", "description", "stage", "segments"):
        if field not in ep:
            problems.append(f"missing field {field}")
    words = 0
    for s in ep.get("segments", []):
        for field in ("name", "turns"):
            if field not in s:
                problems.append(f"segment missing {field}")
        for t in s.get("turns", []):
            if "pause" in t:
                continue
            if t.get("voice") not in VOICES:
                problems.append(f"unknown voice {t.get('voice')} in {s.get('name')}")
            words += len(t.get("text", "").split())
    stage = STAGES.get(ep.get("stage"))
    if stage:
        target = stage["target_words"]
        if not (target * 0.75 <= words <= target * 1.35):
            problems.append(f"word count {words} outside {target}±budget")
    if problems:
        failures += 1
        print(f"FAIL {name}: " + "; ".join(sorted(set(problems))[:5]))
    else:
        print(f"OK   {name}: {words}w stage={ep.get('stage')} new={len(ep.get('vocab_new', []))}")

sys.exit(1 if failures else 0)
