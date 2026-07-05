# «La Señal» — 365-Day Comprehensible-Input Spanish Podcast: Design Spec

Date: 2026-07-05 · Status: Approved by Dane

## Goal

A serialized, audio-only Spanish acquisition podcast built on comprehensible-input
principles (Krashen i+1), taking one learner (Dane) from A2/low-B1 listening to
native-speed (C1-ish) comprehension over 365 days. Target dialects: Colombian and
Venezuelan Spanish. Finished, listenable audio delivered to Apple Podcasts on
iPhone via a private-by-obscurity RSS feed.

## Learner calibration

- Grammar ahead of listening: solid present/preterite/imperfect, early subjunctive.
- Listening: Dreaming Spanish Beginner→Intermediate transition.
- Day 0 = a 10–15 min diagnostic episode: graduated passages at rising
  speed/complexity, each followed by spoken comprehension checks; self-scored
  against a written key. Result sets Day 1 parameters.
- Recalibration mini-test embedded every ~30 days (end of each arc). Dane's
  self-score feeds the next month's difficulty via the monthly authoring session.

## Show design

**Format:** one continuous year-long saga, «La Señal», in 12 monthly arcs.
- Premise: a radio-astronomer in Bogotá (Dra. Camila Rey) and a Venezuelan
  migrant engineer in Medellín (Andrés Materán) discover a signal that is not
  from Earth; the discovery becomes a political power struggle over who controls
  it (sci-fi mystery × political drama).
- Humor via recurring comic characters (notably El Flaco, a conspiracy-theorist
  Bogotá taxi driver who is also a plot engine).
- Cultural grounding: set in Bogotá, Medellín, the llanos, Caracas/Maracaibo in
  flashback; regional slang introduced in context and logged.

**Episode anatomy (every day):**
1. *Anteriormente* — recap cold-open (spaced repetition built in)
2. *Story chapter* — the serialized drama
3. *Mundo Real* — true documentary segment tied to the chapter theme
4. *Repaso* — narrative-circling review recycling recent vocabulary

**Cadence:** one episode daily; duration ramps with listening stamina and level:
days 1–30 ≈ 20 min; 31–90 ≈ 30; 91–180 ≈ 40; 181–270 ≈ 50; 271–365 ≈ 60.
Total ≈ 245 audio-hours (vs 365 for fixed hour-longs).

**Reasoning for serialization:** a known world and cast reduce cold decoding
load, so more attention goes to acquiring new language; variety comes from the
in-episode documentary segment, not from resetting the setting.

## Pedagogy engine

- `curriculum/ledger.json`: every introduced word/structure with first-seen day
  and recycling schedule (reappearances at ~1/3/7/21/60 days). Script generation
  reads the ledger; scripts may not introduce unscheduled items.
- Speed ramp: early episodes use short sentences, deliberate pacing, and
  inserted inter-sentence pauses (assembly-time silence), thinning over months;
  natural native pace by the back half of the year.
- English: only in Day-0 test instructions and ≤10s framings in week 1.
- No explicit grammar instruction; structures acquired through context,
  repetition, and circling.

## Audio production

- Engine: local Chatterbox multilingual TTS (chatterbox-tts 0.1.7,
  `ChatterboxMultilingualTTS`, `language_id="es"`) on M1 Pro via MPS. $0 cost.
- Voices: cloned from CC-BY-SA 4.0 reference clips — OpenSLR SLR72 (Colombian)
  and SLR75 (Venezuelan) crowdsourced speech corpora (© Google 2018–19),
  attributed in show notes. One consistent narrator voice + distinct recurring
  character voices, fixed for the whole year in `voices/voicebank.json`.
- Render: per-dialogue-turn synthesis → quality gate (Whisper ASR round-trip
  compare, retry on mismatch) → ffmpeg concat with scripted pauses → loudnorm
  −16 LUFS → mono 64 kbps 44.1 kHz MP3 (~10–30 MB/episode).
- Disk discipline (host Mac has ~15 GB free): WAV chunks deleted after episode
  assembly; MP3 deleted after upload; repo keeps only scripts, transcripts,
  vocab logs, ledger, feed.

## Publishing

- Public GitHub repo (`la-senal-podcast`): MP3s as Release assets; RSS 2.0 +
  iTunes-namespace `feed.xml` and 3000×3000 cover art on GitHub Pages.
- Followed in Apple Podcasts via Follow a Show by URL — no directory listing,
  no Apple review. (Public-directory submission via Podcasts Connect remains an
  option later, using the same feed.)

## Production strategy (adaptive pipeline)

- Now: full story bible + 365-day curriculum map; Day 0 + days 1–35 scripted,
  rendered, published.
- Nightly launchd job renders/publishes any pending scripts, keeping ~30 days
  of buffer ahead of listening.
- Monthly ~10-min recalibration session with Claude: reads recalibration score
  + ledger, writes the next arc at adjusted i+1. Pre-rendering the whole year
  is deliberately avoided: it would freeze the difficulty curve the
  recalibration checkpoints exist to adjust.

## Per-episode deliverables

MP3 (feed), full transcript (`transcripts/`), vocabulary/grammar log of
new + recycled items (`vocab-logs/`, also summarized in episode show notes).

## Cost reference (computed 2026-07)

ElevenLabs full-year equivalent (~16.8 M chars at 60 min/day; ~11 M chars at
ramped durations): Multilingual v2 at 1 credit/char ≈ $2,970 (Business ×3 mo)
to $2,990 (Scale ×10 mo); Flash v2.5 at ~0.5 credit/char ≈ $1,500 (Scale ×5 mo).
Ramped-duration year ≈ $900–1,800. Local Chatterbox: $0 + electricity + wall-clock
(measured RTF reported in final build report).
