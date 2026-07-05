# Script-writing guide (for episode authors)

You are writing one episode of «La Señal», a comprehensible-input Spanish
podcast. The listener is an A2/low-B1 English speaker training aural decoding.
Read `curriculum/story-bible.md`, `curriculum/level-map.json`, and
`curriculum/arc1-beats.md` before writing. `scripts/ep000.json` shows the JSON
format.

## Hard rules

1. **Vocabulary discipline.** You may use: (a) high-frequency A2 vocabulary
   (Hugo's Spanish in Three Months through ~p160 level), (b) items introduced
   on PREVIOUS days per arc1-beats.md, (c) TODAY's new items — and nothing
   else. If a beat needs a word outside this, rephrase or gloss it through
   context immediately.
2. **Every new item is circled**: used at least `min_uses_per_new_item` times
   (see level-map stage), in varied sentences, with the narrator making meaning
   unmistakable through context, contrast, or paraphrase — never translation.
   Example circling: «Camila graba el ruido. ¿Graba? Sí: guarda el sonido en la
   computadora, para escucharlo después. Graba el ruido.»
3. **No English.** Exception: days 1–7 may open with ≤10 seconds of English
   framing. Show notes (`description`) are in English.
4. **Grammar scope** per stage (level-map.json). Grammar the listener knows but
   hasn't automatized (preterite/imperfect) is welcome; stay inside scope.
5. **Sentence length** ≤ stage max_sentence_words for narrator scaffolding.
   Character dialogue may occasionally run slightly longer if the content is
   predictable from context.
6. **Word budget**: stage target_words ±10%.
7. **Voices**: only these ids — narrator, camila, andres, elflaco, ochoa,
   chela, pardo, marta, julio, sarmiento, aux_f, aux_m.
8. **Story bible is law**: character voice/personality, arc beats, humor
   engines. Beats are a skeleton — flesh them out with scenes, but land every
   beat listed for the day.

## Episode structure (segments array, in order)

1. `anteriormente` — 60–90s recap of the story so far, weighted to yesterday
   (skip on day 1). Recap = spaced repetition: reuse recent vocab deliberately.
2. `historia-1`, `historia-2`, … — the drama, in 2–4 scene segments.
3. `mundo-real` — the documentary segment (topic in beats), narrator-led,
   3–5 min of true, interesting content at the same language level.
4. `repaso` — 2–3 min narrative-circling review of today's new items (retell
   micro-moments of the episode using them; ask rhetorical questions and
   answer them). End with one line teasing tomorrow.

## Segment JSON fields (S1 days 1–30 / S2 days 31–35)

- `"lang": "es"`, `"atempo"`: 0.93 / 0.96
- `"inter_sentence_pause_s"`: 1.3 / 0.9
- `"inter_turn_pause_s"`: 1.6 / 1.2
- Dialogue-heavy segments may reduce inter_sentence_pause_s by 0.2 for flow.
- Use `{"pause": N}` turns for dramatic beats (1.5–3s).

## Top-level JSON fields

`episode` ("001"…), `day`, `arc`, `title` (from beats), `description`
(English, 1–2 sentences, no spoilers beyond the episode), `stage`,
`duration_target_min`, `segments`, `vocab_new` ([{term, gloss}] — gloss in
English, for the show notes/log only), `vocab_recycled` (items from days at
offsets 1/3/7/21 that you actually reused), `show_notes_extra` (optional).

## Tone

Never textbook. The narrator is a character: warm, wry, loves the listener.
Humor must land in-world (El Flaco's theories, arepa war, Chela's voice notes,
Pardo's mangled proverbs). Cliffhangers earn tomorrow's listen. Emotional
beats get room to breathe (use pauses).

## Day 30 exception

Day 30 is the in-world recalibration test («Prueba y promesa», framed as El
Flaco testing his podcast audience): five passages retelling the month's story
at graduated difficulty — passages 1–3 at S1 pace (atempo 0.93), passage 4 at
S2 (0.96, shorter pauses), passage 5 at S3 (1.0, minimal pauses) — each
followed by three spoken questions with 5s answer pauses and spoken answers,
mirroring ep000's structure. Recycle-only; no new vocabulary. Scoring guide
goes in show_notes_extra.
