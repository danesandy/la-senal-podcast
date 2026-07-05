# La Señal — Operations Runbook

## How the machine works

- `scripts/epNNN.json` — episode scripts (the queue). Anything here that isn't
  in `episodes.json` yet is pending production.
- `tools/produce.sh` — renders + publishes every pending script, in order.
  Runs automatically via launchd at **01:00 and 13:00 daily**
  (`~/Library/LaunchAgents/com.lasenal.produce.plist`). Safe to run manually
  any time: `bash tools/produce.sh`. A lock prevents double-runs.
- Rendering: local Chatterbox multilingual TTS on MPS, ~5× real-time
  (a 20-min episode ≈ 100 min of compute). Each episode is Whisper-QC'd,
  loudness-normalized, uploaded to a GitHub Release, added to `feed.xml`,
  pushed — then deleted locally. Disk footprint stays small.
- Feed: https://danesandy.github.io/la-senal-podcast/feed.xml
- Log: `audio-work/produce.log`

## Keep the Mac able to render

- Keep it plugged in. `caffeinate -i` prevents idle-sleep during renders, but
  a closed lid still sleeps the machine — leave the lid open overnight when a
  batch is pending, or set "Prevent automatic sleeping on power adapter" in
  System Settings → Displays → Advanced.
- If the queue falls behind (life happens), just run `bash tools/produce.sh`
  and leave it; it catches up at ~4–5 hours of audio per 24h.

## Monthly recalibration session (~10 min, every ~30 days)

Trigger: you've listened to the day-30/60/90… test episode («Prueba») and have
your self-score.

1. Open Claude Code in this project and say:
   *"Recalibration: my day-N test score was X/15. Passages that felt easy: …;
   hard: …. Write the next arc."*
2. Claude then: adjusts `curriculum/level-map.json` stage parameters if needed
   (pace up if ≥12, hold if 7–11, add repetition/slow ramp if ≤6), writes the
   next arc's beat sheet + vocab schedule following `curriculum/story-bible.md`,
   fans out script-writing agents (see `curriculum/script-writing-guide.md`),
   rebuilds `curriculum/ledger.json`, and commits.
3. The nightly job renders the new scripts automatically. Nothing else to do.

## Adding a one-off episode or fixing one

- Edit or add `scripts/epNNN.json`, then `bash tools/produce.sh`.
- To re-render an already-published episode: remove its entry from
  `episodes.json`, delete its GitHub release
  (`gh release delete ep-NNN -y -R danesandy/la-senal-podcast`), then produce.

## Voices

`voices/voicebank.json` maps characters to reference WAVs in `voices/bank/`
(built from OpenSLR SLR72/SLR75, CC-BY-SA 4.0). Never change a principal's
ref. New characters: assign from `reserved` in that file.

## If something breaks

- Render fails: check `audio-work/produce.log`; the render resumes from its
  per-chunk cache, so re-running is cheap.
- Feed problems: validate at https://podba.se/validate/ or
  https://castfeedvalidator.com with the feed URL.
- Episode audio sounds wrong (garbled turn): re-render that episode (above) —
  the Whisper QC gate catches most cases automatically.
