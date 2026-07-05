#!/usr/bin/env python3
"""Compile curriculum/ledger.json from the beats files' vocab schedules.

Parses every curriculum/arc*-beats.md for '## Día N' headers and '**New:**'
lines (items separated by '·'). The ledger is the machine-readable index of
what was introduced when, plus each item's recycling due-days.
"""
import json
import os
import re
import glob

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFSETS = [1, 3, 7, 21, 60]


def main():
    items = []
    for beats in sorted(glob.glob(os.path.join(PROJ, "curriculum", "arc*-beats.md"))):
        with open(beats) as f:
            text = f.read()
        day = None
        for line in text.splitlines():
            m = re.match(r"## Día (\d+)", line)
            if m:
                day = int(m.group(1))
                continue
            m = re.match(r"\*\*New:\*\*\s*(.+)", line)
            if m and day is not None:
                raw = m.group(1)
                if raw.startswith("(none"):
                    continue
                for term in raw.split("·"):
                    term = term.strip()
                    term = re.sub(r"\(.*?\)", "", term).strip(" ·").strip()
                    if term:
                        items.append({
                            "term": term,
                            "day": day,
                            "recycle_due": [day + o for o in OFFSETS],
                        })
    out = os.path.join(PROJ, "curriculum", "ledger.json")
    with open(out, "w") as f:
        json.dump({"items": items, "count": len(items)}, f, indent=2, ensure_ascii=False)
    print(f"ledger: {len(items)} items across days "
          f"{min(i['day'] for i in items)}–{max(i['day'] for i in items)}")


if __name__ == "__main__":
    main()
