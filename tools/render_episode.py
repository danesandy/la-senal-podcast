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
# launchd runs with a minimal PATH; ensure Homebrew tools (ffmpeg, ffprobe,
# whisper-cli) are findable even when invoked outside an interactive shell.
os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")
VOICEBANK = os.path.join(PROJ, "voices", "voicebank.json")
WORK = os.path.join(PROJ, "audio-work")
OUT = os.path.join(PROJ, "audio-work", "out")
WHISPER_MODEL = os.path.expanduser("~/.cache/whisper-cpp/ggml-small.bin")
WHISPER_CLI = shutil.which("whisper-cli") or "/opt/homebrew/bin/whisper-cli"
MAX_CHUNK_CHARS = 140    # short chunks: Chatterbox loops far less on shorter text
QC_THRESHOLD = 0.70
QC_RETRIES = 2

class RenderCrashed(RuntimeError):
    """Generation failed outright — abort rather than ship silence."""

_model = None


def _patch_s3gen_resampler_for_mps():
    """Chatterbox's s3gen.embed_ref resamples the voice reference clip with
    torchaudio's sinc-resample kernel on whatever device the model is on. On
    MPS that kernel hits Apple's Metal conv output-channel limit
    (NotImplementedError: Output channels > 65536), unfixed as of torch 2.11 —
    every generate() call crashes before it produces audio. This is a one-time
    per-voice-reference resample (not per-chunk), so run it on CPU and hand
    the result back on the original device; everything downstream of it is
    untouched."""
    import torchaudio as ta
    import chatterbox.models.s3gen.s3gen as s3gen_mod

    def cpu_safe_get_resampler(src_sr, dst_sr, device):
        resampler = ta.transforms.Resample(src_sr, dst_sr)  # stays on CPU

        def call(wav):
            return resampler(wav.to("cpu")).to(device)
        return call

    s3gen_mod.get_resampler = cpu_safe_get_resampler


def _patch_alignment_analyzer_short_text_crash():
    """chatterbox.models.t3.inference.alignment_stream_analyzer.step() computes
    `A[self.completed_at:, :-5].max(dim=1)` to detect repetition. For very
    short chunks (e.g. a standalone "No.", ~2 tokens) the text-token dimension
    is <= 5 wide, so the slice is zero-width and .max(dim=1) raises
    `IndexError: max(): Expected reduction dim 1 to have non-zero size` on
    every single attempt — this is deterministic, not a flaky MPS crash, so
    retries never help and the chunk fails outright. Patching the class
    in-memory would mean re-implementing all ~90 lines of step() (fragile,
    drifts from upstream); instead patch the installed source file on disk,
    once, idempotently, so it stays a 1-line diff that's easy to verify against
    upstream chatterbox releases."""
    import chatterbox.models.t3.inference.alignment_stream_analyzer as mod
    path = mod.__file__
    src = open(path).read()
    marker = "_rep_tail.shape[1] > 0"
    if marker in src:
        return  # already patched
    old = "alignment_repetition = self.complete and (A[self.completed_at:, :-5].max(dim=1).values.sum() > 5)"
    if old not in src:
        raise RuntimeError(
            f"{path} does not match the version this patch targets — "
            "chatterbox-tts likely upgraded; check alignment_stream_analyzer.py by hand."
        )
    new = (
        "_rep_tail = A[self.completed_at:, :-5]\n"
        "        alignment_repetition = self.complete and _rep_tail.shape[1] > 0 and (_rep_tail.max(dim=1).values.sum() > 5)"
    )
    open(path, "w").write(src.replace(old, new, 1))
    print("[render] patched alignment_stream_analyzer.py (short-text IndexError guard)", flush=True)


def get_model():
    global _model
    if _model is None:
        import torch
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        if device == "mps":
            _patch_s3gen_resampler_for_mps()
        _patch_alignment_analyzer_short_text_crash()
        print(f"[render] loading ChatterboxMultilingualTTS on {device}...", flush=True)
        t0 = time.time()
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        _model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        print(f"[render] model loaded in {time.time()-t0:.0f}s", flush=True)
    return _model


def split_sentences(text):
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return [p for p in parts if p]


MIN_CHUNK_CHARS = 8   # below this, Chatterbox's alignment-stream analyzer can
                      # IndexError on every attempt (too few tokens generated
                      # for its lookback window) — e.g. a standalone "No."


def merge_short_chunks(chunks):
    """Fold any chunk shorter than MIN_CHUNK_CHARS into a neighbor so it's
    never synthesized standalone. Merges into the previous chunk when one
    exists (keeps chunk count/pause placement simple); falls back to the
    next chunk for a short chunk at the very start."""
    if len(chunks) <= 1:
        return chunks
    merged = list(chunks)
    i = 0
    while i < len(merged):
        if len(merged[i]) >= MIN_CHUNK_CHARS or len(merged) <= 1:
            i += 1
            continue
        if i > 0:
            merged[i - 1] = f"{merged[i - 1]} {merged[i]}".strip()
            del merged[i]
            # don't advance i — re-check the (now longer) merged[i-1] isn't
            # itself short, and the new merged[i] (old i+1) for shortness
            i = max(i - 1, 0)
        else:
            merged[1] = f"{merged[0]} {merged[1]}".strip()
            del merged[0]
    return merged


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


GEN_TRIES = 6
SPEECH_MIN_CREST = 5.0   # good speech measures ~7–12; static ~1–3.5


def speech_quality(wav_tensor, sr):
    """Score how speech-like a waveform is. Chatterbox on MPS intermittently
    emits sustained noise/static (uniform, low crest factor) instead of speech,
    or near-silence. Returns a crest-factor-based score; higher = more
    speech-like. Static reads ~1–3.5, real speech ~4–12."""
    import torch
    x = wav_tensor.flatten().float()
    if x.numel() < int(sr * 0.15):
        return 99.0  # too short to judge (tiny words) — accept
    rms = x.pow(2).mean().sqrt().item()
    peak = x.abs().max().item()
    if rms < 1e-4:
        return 0.0   # dead silence where speech was expected
    return peak / (rms + 1e-9)


CHUNK_QC_SIM = 0.62      # per-chunk whisper match to accept a take


CHARS_PER_SEC = 15.0     # fast Spanish/English narration rate


def take_score(wav, sr, text, lang, tmp_path):
    """Ground-truth quality of one generated take. Catches every Chatterbox
    failure mode that audio-only metrics miss:
      • runaway loop/drone — take runs far longer than the text warrants
        (the ep000 bug: a 3s line generated as a 90s repeating loop). Caught
        by a duration sanity check BEFORE Whisper, since the loop's clean head
        would otherwise pass the word-match.
      • tonal drone / static burst — low crest, or Whisper hears no words.
      • wrong / dropped words — low Whisper similarity.
    Returns a 0..1 score. Short texts fall back to a liveness check."""
    import torchaudio
    dur = wav.shape[-1] / sr
    expected = max(1.0, len(text) / CHARS_PER_SEC)
    if dur > expected * 2.5 + 2.0:        # runaway generation — reject outright
        return 0.0
    crest = speech_quality(wav, sr)
    if crest < 2.5:                       # dead/static take — skip whisper
        return 0.0
    torchaudio.save(tmp_path, wav, sr)
    got = transcribe(tmp_path, lang)
    n_words = len(norm_text(text).split())
    if n_words <= 2:
        # can't trust similarity on 1–2 words; require non-empty + live audio
        return 1.0 if (got.strip() and crest >= 3.2) else 0.2
    return similarity(text, got)


def synth_chunk(model, text, lang, voice_cfg, out_path):
    """Generate one chunk, self-healing against Chatterbox's stochastic
    failures: catches generation crashes (alignment-analyzer IndexError etc.)
    and rejects bad takes by Whisper round-trip, retrying and keeping the best."""
    import torch
    import torchaudio
    kwargs = {
        "language_id": lang,
        "audio_prompt_path": voice_cfg["ref"],
    }
    if "exaggeration" in voice_cfg:
        kwargs["exaggeration"] = voice_cfg["exaggeration"]
    if "cfg_weight" in voice_cfg:
        kwargs["cfg_weight"] = voice_cfg["cfg_weight"]

    tmp_path = out_path + ".take.wav"
    best_wav, best_score = None, -1.0
    for attempt in range(GEN_TRIES):
        try:
            wav = model.generate(text, **kwargs)
        except Exception as e:
            print(f"[render]   gen attempt {attempt} crashed ({type(e).__name__}); retrying",
                  flush=True)
            continue
        # MPS output can exceed full scale / contain non-finite samples, which
        # crashes LAME's psymodel downstream. Sanitize at the source.
        wav = torch.nan_to_num(wav).clamp(-1.0, 1.0)
        score = take_score(wav, model.sr, text, lang, tmp_path)
        if score > best_score:
            best_wav, best_score = wav, score
        if score >= CHUNK_QC_SIM:
            break
        print(f"[render]   gen attempt {attempt} failed QC "
              f"(match={score:.2f}); retrying", flush=True)

    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    if best_wav is None:
        # Every attempt crashed. Substituting silence here is how 21 episodes
        # shipped as pauses with no speech: a per-chunk failure is almost never
        # isolated (a broken backend fails every chunk), so failing the whole
        # episode loudly is correct. Set SENAL_ALLOW_SILENCE=1 to override for
        # a genuinely one-off bad chunk.
        msg = (f"ALL {GEN_TRIES} generation attempts crashed for: {text[:80]!r}. "
               f"Refusing to substitute silence.")
        if not os.environ.get("SENAL_ALLOW_SILENCE"):
            raise RenderCrashed(msg)
        print(f"[render]   {msg} — SENAL_ALLOW_SILENCE set, inserting silence",
              flush=True)
        best_wav = torch.zeros(1, int(model.sr * 0.4))
    else:
        # Runaway-loop guard: if even the best take is far longer than the text
        # warrants (every retry looped), truncate to the plausible clean length
        # so a repeating drone can never survive into the mix. The correct
        # utterance is at the head; the loop is the tail.
        expected = max(1.0, len(text) / CHARS_PER_SEC)
        max_keep = expected * 1.5 + 1.0
        dur = best_wav.shape[-1] / model.sr
        if dur > max_keep + 1.0:
            keep = int(max_keep * model.sr)
            best_wav = best_wav[:, :keep].clone()
            fade = min(int(0.04 * model.sr), best_wav.shape[-1])
            best_wav[:, -fade:] *= torch.linspace(1.0, 0.0, fade)
            print(f"[render]   truncated runaway take {dur:.0f}s->{max_keep:.0f}s "
                  f"for: {text[:50]!r}", flush=True)
        elif best_score < CHUNK_QC_SIM:
            print(f"[render]   kept best-of-{GEN_TRIES} take (match={best_score:.2f}) "
                  f"for: {text[:50]!r}", flush=True)

    torchaudio.save(out_path, best_wav, model.sr)
    return best_wav.shape[-1] / model.sr


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
            chunks = merge_short_chunks(chunks)
            for ci, chunk in enumerate(chunks):
                key = chunk_key(voice, tlang, chunk)
                cpath = os.path.join(chunks_dir, key + ".wav")
                # Reuse a cached chunk only if it actually matches its text —
                # a static/drone take saved by an earlier run must not survive.
                if os.path.exists(cpath):
                    cw, _ = torchaudio.load(cpath)
                    if take_score(cw, sr, chunk, tlang, cpath + ".chk.wav") < CHUNK_QC_SIM:
                        print(f"[render] ep{ep_id}/{seg_name} [{voice}]: cached chunk "
                              f"failed QC — regenerating", flush=True)
                        os.remove(cpath)
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

        # Per-segment static scan (diagnostic): flag any segment whose assembled
        # .wav contains sustained low-crest loud regions before it reaches the mp3.
        sw, ssr = torchaudio.load(seg_wav)
        xs = sw.flatten().numpy()
        wln = ssr // 2
        sflag = sum(
            1 for k in range(len(xs) // wln)
            if (lambda w: (w**2).mean() ** 0.5 > 0.02 and
                abs(w).max() / ((w**2).mean() ** 0.5 + 1e-9) < 3.2)(xs[k*wln:(k+1)*wln])
        )
        print(f"[render] ep{ep_id}/{seg_name}: SEGSCAN {sflag} static windows", flush=True)

        info = torchaudio.info(seg_wav)
        total_audio_s += info.num_frames / info.sample_rate
        seg_files.append((seg_wav, seg.get("atempo", 1.0)))

    # --- Assembly: atempo per segment, concat, loudnorm, MP3 ---
    concat_list = os.path.join(epdir, "concat.txt")
    tempo_files = []
    for i, (seg_wav, atempo) in enumerate(seg_files):
        tf = os.path.join(epdir, f"tempo_{i:02d}.wav")
        # Force EVERY tempo file to an identical codec/rate/layout. Mixing
        # formats (torchaudio writes f32le; ffmpeg atempo emits s16le) makes the
        # concat demuxer misread one as the other → garbage/static in exactly
        # the atempo!=1.0 segments. Re-encode all, atempo or not.
        af = ["-filter:a", f"atempo={atempo}"] if atempo != 1.0 else []
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", seg_wav, *af,
             "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", tf], check=True)
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

    # --- Cleanup working WAVs (KEEP_WORK=1 preserves them for debugging) ---
    if not os.environ.get("KEEP_WORK"):
        shutil.rmtree(epdir)

    wall = time.time() - t_start
    print(
        f"[render] ep{ep_id} DONE: {dur/60:.1f} min audio, "
        f"{os.path.getsize(mp3_path)/1e6:.1f} MB, wall {wall/60:.1f} min "
        f"-> {mp3_path}",
        flush=True,
    )
    return mp3_path, dur


def acquire_global_lock():
    """Exclusive lock so two renders can never run at once. Concurrent renders
    write the same chunk-cache paths and corrupt each other's WAVs (they read
    back as static/drone) — the cause of the ep000 static. Stale locks from a
    dead process are reclaimed."""
    lockdir = os.path.join(WORK, ".render.lock")
    pidfile = os.path.join(lockdir, "pid")
    for _ in range(2):
        try:
            os.makedirs(lockdir)
            with open(pidfile, "w") as f:
                f.write(str(os.getpid()))
            return lockdir
        except FileExistsError:
            try:
                with open(pidfile) as f:
                    other = int(f.read().strip())
                os.kill(other, 0)  # alive?
                print(f"[render] another render (pid {other}) holds the lock — exiting",
                      flush=True)
                sys.exit(0)
            except (ProcessLookupError, ValueError, FileNotFoundError):
                print("[render] reclaiming stale render lock", flush=True)
                shutil.rmtree(lockdir, ignore_errors=True)
    print("[render] could not acquire lock — exiting", flush=True)
    sys.exit(0)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    os.makedirs(WORK, exist_ok=True)
    lockdir = acquire_global_lock()
    import atexit
    atexit.register(lambda: shutil.rmtree(lockdir, ignore_errors=True))
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
