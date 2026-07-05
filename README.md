# La Señal

A serialized sci-fi / political-drama podcast in Colombian and Venezuelan
Spanish, engineered as a 365-day comprehensible-input curriculum for one
learner. Produced entirely with local TTS (Chatterbox multilingual, voice
cloning) and published as a personal podcast feed.

**Feed:** https://danesandy.github.io/la-senal-podcast/feed.xml

- `curriculum/` — story bible, level map, beat sheets, vocabulary ledger
- `scripts/` — episode scripts (structured JSON: segments → speaker turns)
- `tools/` — render pipeline (TTS → Whisper QC → loudnorm → MP3), feed
  generator, publisher, queue runner
- `transcripts/`, `vocab-logs/` — per-episode deliverables
- `feed.xml`, `cover.jpg` — served via GitHub Pages; audio lives in Releases

See `RUNBOOK.md` for operations and `docs/superpowers/specs/` for the design.

## Voice attribution

Character voices are cloned from reference clips in the crowdsourced
[OpenSLR SLR72 (Colombian Spanish)](https://www.openslr.org/72/) and
[SLR75 (Venezuelan Spanish)](https://www.openslr.org/75/) corpora,
© Google 2018–2019, licensed CC-BY-SA 4.0. This project's audio is personal,
non-commercial output.
