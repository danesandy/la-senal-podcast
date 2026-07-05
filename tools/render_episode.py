#!/usr/bin/env python3
"""
La Señal — episode renderer.

Renders one or more episode script JSONs to podcast-ready MP3s using local
Chatterbox multilingual TTS (voice cloning per character) on MPS.

Usage (inside the chatterbox venv):
  python render_episode.py scripts/ep000.json [scripts/ep001.json ...]

Design:
- Per-turn synthesis, chunked to <=280 chars at sentence boundaries.
- Chunk WAVs cached on disk (md5 of voice+lang+text) -> interrupted renders resume.
- Quality gate: each segment is Whisper-transcribed (whisper.cpp, small model)
  and fuzzy-compared to the script text; failing segments get per-chunk
  drill-down and regeneration (up to 2 retries, best take kept).
- Assembly: scripted pauses -> per-segment atempo -> concat -> loudnorm
  (-16 LUFS) -> mono 64kbps 44.1kHz MP3. Transcript + show notes emitted.
- WAV working files are deleted after a successful MP3 (disk is tight).
"""

import sys
import os
import re
import json
import hashlib
import shutil
import subprocess
import time
import difflib
import unicodedata

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOICEBANK = os.path.join(PROJ, "voices", "voicebank.json")
WORK = os.path.join(PROJ, "audio-work")
OUT = os.path.join(PROJ, "audio-work", "out")
WHISPER_MODEL = os.path.expanduser("~/.cache/whisper-cpp/ggml-small.bin")
WHISPER_CLI = shutil.which("whisper-cli") or "/opt/homebrew/bin/whisper-cli"
MAX_CHUNK_CHARS = 280
QC_THRESHOLD = 0.70
QC_RETRIES = 2

_model = None


def get_model():
    global _model
    if _model is None:
        import torch
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        print(f"[render] loading ChatterboxMultilingualTTS on {device}...", flush=True)
        t0 = time.time()
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        _model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        print(f"[render] model loaded in {time.time()-t0:.0f}s", flush=True)
    return _model


def split_sentences(text):
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return [p for p in parts if p]


def chunk_sentences(sentences):
    """Group sentences into chunks of <= MAX_CHUNK_CHARS."""
    chunks, cur = [], ""
    for s in sentences:
        if cur and len(cur) + 1 + len(s) > MAX_CHUNK_CHARS:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def norm_text(t):
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-zñü0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def similarity(a, b):
    # Word-level with autojunk off: char-level SequenceMatcher's autojunk
    # heuristic silently tanks ratios on texts >200 chars.
    return difflib.SequenceMatcher(
        None, norm_text(a).split(), norm_text(b).split(), autojunk=False
    ).ratio()


def transcribe(wav_path, lang):
    """Whisper.cpp transcription. Input must be 16k mono wav; we convert."""
    tmp16 = wav_path + ".16k.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", wav_path, "-ar", "16000", "-ac", "1", tmp16],
        check=True,
    )
    try:
        r = subprocess.run(
            [WHISPER_CLI, "-m", WHISPER_MODEL, "-l", lang, "-np", "-nt", tmp16],
            capture_output=True, text=True, timeout=600,
        )
        return r.stdout.strip()
    finally:
        os.remove(tmp16)


def synth_chunk(model, text, lang, voice_cfg, out_path):
    import torchaudio
    kwargs = {
        "language_id": lang,
        "audio_prompt_path": voice_cfg["ref"],
    }
    if "exaggeration" in voice_cfg:
        kwargs["exaggeration"] = voice_cfg["exaggeration"]
    if "cfg_weight" in voice_cfg:
        kwargs["cfg_weight"] = voice_cfg["cfg_weight"]
    wav = model.generate(text, **kwargs)
    # MPS output can exceed full scale / contain non-finite samples, which
    # crashes LAME's psymodel downstream. Sanitize at the source.
    import torch
    wav = torch.nan_to_num(wav).clamp(-1.0, 1.0)
    torchaudio.save(out_path, wav, model.sr)
    return wav.shape[-1] / model.sr


def chunk_key(voice, lang, text):
    return hashlib.md5(f"{voice}|{lang}|{text}".encode()).hexdigest()


def render_episode(script_path, voicebank, _depth=0):
    import torch
    import torchaudio

    with open(script_path) as f:
        ep = json.load(f)
    ep_id = ep["episode"]
    epdir = os.path.join(WORK, f"ep{ep_id}")
    chunks_dir = os.path.join(epdir, "chunks")
    seg_dir = os.path.join(epdir, "segments")
    os.makedirs(chunks_dir, exist_ok=True)
    os.makedirs(seg_dir, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    model = get_model()
    sr = model.sr
    t_start = time.time()
    total_audio_s = 0.0
    seg_files = []

    for seg in ep["segments"]:
        seg_name = seg["name"]
        seg_wav = os.path.join(seg_dir, f"{seg_name}.wav")
        lang = seg.get("lang", "es")
        isp = seg.get("inter_sentence_pause_s", 0.5)
        itp = seg.get("inter_turn_pause_s", 0.8)
        if os.path.exists(seg_wav):
            seg_files.append((seg_wav, seg.get("atempo", 1.0)))
            info = torchaudio.info(seg_wav)
            total_audio_s += info.num_frames / info.sample_rate
            print(f"[render] ep{ep_id}/{seg_name}: cached", flush=True)
            continue

        pieces = []          # (tensor | None, silence_s) — audio pieces in order
        seg_texts = []       # for QC
        chunk_records = []   # (chunk_path, text) for drill-down

        def add_silence(seconds):
            pieces.append(torch.zeros(1, int(sr * seconds)))

        for turn in seg["turns"]:
            if "pause" in turn:
                add_silence(turn["pause"])
                continue
            voice = turn["voice"]
            vcfg = voicebank[voice]
            tlang = turn.get("lang", lang)
            sentences = split_sentences(turn["text"])
            # For scaffolded stages we want silence BETWEEN sentences, so
            # synthesize chunk = one sentence when pauses are large, else group.
            if isp >= 0.5:
                chunks = sentences
            else:
                chunks = chunk_sentences(sentences)
            for ci, chunk in enumerate(chunks):
                key = chunk_key(voice, tlang, chunk)
                cpath = os.path.join(chunks_dir, key + ".wav")
                if not os.path.exists(cpath):
                    t0 = time.time()
                    dur = synth_chunk(model, chunk, tlang, vcfg, cpath)
                    print(
                        f"[render] ep{ep_id}/{seg_name} [{voice}] "
                        f"{len(chunk)}ch -> {dur:.1f}s in {time.time()-t0:.0f}s",
                        flush=True,
                    )
                wav, wsr = torchaudio.load(cpath)
                pieces.append(wav)
                chunk_records.append((cpath, chunk, voice, tlang, vcfg))
                if ci < len(chunks) - 1:
                    add_silence(isp)
            seg_texts.append(turn["text"])
            add_silence(itp)

        seg_tensor = torch.cat([p for p in pieces], dim=1)
        torchaudio.save(seg_wav, seg_tensor, sr)

        # --- QC gate: whisper the whole segment, compare to script text ---
        expected = " ".join(seg_texts)
        if expected.strip():
            got = transcribe(seg_wav, lang)
            ratio = similarity(expected, got)
            print(f"[render] ep{ep_id}/{seg_name}: QC similarity {ratio:.2f}", flush=True)
            if ratio < QC_THRESHOLD:
                print(f"[render] ep{ep_id}/{seg_name}: QC FAIL — drilling into chunks", flush=True)
                regenerated = False
                for cpath, ctext, cvoice, clang, cvcfg in chunk_records:
                    cgot = transcribe(cpath, clang)
                    cratio = similarity(ctext, cgot)
                    if cratio < QC_THRESHOLD:
                        best_ratio, best_path = cratio, None
                        for attempt in range(QC_RETRIES):
                            rpath = cpath + f".retry{attempt}.wav"
                            synth_chunk(model, ctext, clang, cvcfg, rpath)
                            rgot = transcribe(rpath, clang)
                            rratio = similarity(ctext, rgot)
                            print(
                                f"[render]   retry {attempt} [{cvoice}] {cratio:.2f} -> {rratio:.2f}",
                                flush=True,
                            )
                            if rratio > best_ratio:
                                best_ratio, best_path = rratio, rpath
                            if rratio >= QC_THRESHOLD:
                                break
                        if best_path:
                            shutil.move(best_path, cpath)
                            regenerated = True
                        for attempt in range(QC_RETRIES):
                            rp = cpath + f".retry{attempt}.wav"
                            if os.path.exists(rp):
                                os.remove(rp)
                if regenerated and _depth < 3:
                    os.remove(seg_wav)
                    print(f"[render] ep{ep_id}/{seg_name}: reassembling after retries", flush=True)
                    return render_episode(script_path, voicebank, _depth + 1)  # resume via cache

        info = torchaudio.info(seg_wav)
        total_audio_s += info.num_frames / info.sample_rate
        seg_files.append((seg_wav, seg.get("atempo", 1.0)))

    # --- Assembly: atempo per segment, concat, loudnorm, MP3 ---
    concat_list = os.path.join(epdir, "concat.txt")
    tempo_files = []
    for i, (seg_wav, atempo) in enumerate(seg_files):
        tf = os.path.join(epdir, f"tempo_{i:02d}.wav")
        if atempo != 1.0:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", seg_wav,
                 "-filter:a", f"atempo={atempo}", tf], check=True)
        else:
            shutil.copy(seg_wav, tf)
        tempo_files.append(tf)
    with open(concat_list, "w") as f:
        for tf in tempo_files:
            f.write(f"file '{tf}'\n")

    mp3_path = os.path.join(OUT, f"ep{ep_id}.mp3")
    title = ep.get("title", f"Episodio {ep_id}")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", concat_list,
         "-af", "alimiter=limit=0.97,loudnorm=I=-16:TP=-1.5:LRA=11",
         "-ar", "44100", "-ac", "1", "-b:a", "64k",
         "-metadata", f"title={title}",
         "-metadata", "artist=La Señal",
         "-metadata", "album=La Señal — Spanish por input comprensible",
         mp3_path], check=True)

    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", mp3_path],
        capture_output=True, text=True).stdout.strip())

    # --- Transcript ---
    tr_path = os.path.join(PROJ, "transcripts", f"ep{ep_id}.md")
    with open(tr_path, "w") as f:
        f.write(f"# {title}\n\n")
        for seg in ep["segments"]:
            f.write(f"## {seg['name']}\n\n")
            for turn in seg["turns"]:
                if "pause" in turn:
                    continue
                f.write(f"**{turn['voice']}:** {turn['text']}\n\n")

    # --- Vocab log ---
    if ep.get("vocab_new") or ep.get("vocab_recycled"):
        vl_path = os.path.join(PROJ, "vocab-logs", f"ep{ep_id}.md")
        with open(vl_path, "w") as f:
            f.write(f"# Vocabulario — {title}\n\n## Nuevo\n\n")
            for item in ep.get("vocab_new", []):
                f.write(f"- **{item['term']}** — {item['gloss']}\n")
            f.write("\n## Reciclado\n\n")
            for term in ep.get("vocab_recycled", []):
                if isinstance(term, dict):
                    f.write(f"- {term.get('term')} (día {term.get('from_day', '?')})\n")
                else:
                    f.write(f"- {term}\n")

    # --- Cleanup working WAVs ---
    shutil.rmtree(epdir)

    wall = time.time() - t_start
    print(
        f"[render] ep{ep_id} DONE: {dur/60:.1f} min audio, "
        f"{os.path.getsize(mp3_path)/1e6:.1f} MB, wall {wall/60:.1f} min "
        f"-> {mp3_path}",
        flush=True,
    )
    return mp3_path, dur


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if not os.path.exists(WHISPER_MODEL):
        os.makedirs(os.path.dirname(WHISPER_MODEL), exist_ok=True)
        print("[render] downloading whisper.cpp small model for QC...", flush=True)
        subprocess.run(
            ["curl", "-sSL", "-o", WHISPER_MODEL,
             "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"],
            check=True)
    with open(VOICEBANK) as f:
        voicebank = json.load(f)["voices"]
    for script_path in sys.argv[1:]:
        render_episode(script_path, voicebank)


if __name__ == "__main__":
    main()
