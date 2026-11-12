#!/usr/bin/env python3
"""Transcribe a rip's English audio and write subtitles that match the spoken
dub wording, instead of the disc's translation of the Japanese script.

Run inside the venv built beside this file:

    asr/venv/bin/python asr/transcribe.py --input FILE --output FILE.srt
        [--model large-v3-turbo] [--audio-stream 0] [--max-chars 42]

Progress is printed as "PROGRESS <percent>" lines; anything else on stdout is
a log line for the app's diagnostics file.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NV = os.path.join(HERE, "venv", "lib", "python3.12", "site-packages", "nvidia")


def cuda_libs():
    """Load the pip-installed CUDA/cuDNN wheels.

    LD_LIBRARY_PATH is only read when the process starts, so setting it at
    runtime does not help a library dlopen'd later — preload with ctypes
    instead, and keep the env var for anything we spawn.
    """
    dirs = []
    for part in ("cublas", "cudnn", "cuda_nvrtc", "cuda_runtime"):
        d = os.path.join(NV, part, "lib")
        if os.path.isdir(d):
            dirs.append(d)
    if not dirs:
        return
    old = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = ":".join(dirs + ([old] if old else []))
    import ctypes
    names = [
        "libcublasLt.so.12", "libcublas.so.12",
        "libcudnn.so.9", "libcudnn_graph.so.9", "libcudnn_ops.so.9",
        "libcudnn_engines_precompiled.so.9", "libcudnn_heuristic.so.9",
        "libcudnn_engines_runtime_compiled.so.9",
    ]
    for name in names:
        for d in dirs:
            path = os.path.join(d, name)
            if os.path.exists(path):
                try:
                    ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                except OSError as exc:
                    print("preload failed %s: %s" % (name, exc), flush=True)
                break


def srt_time(seconds):
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000.0))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def wrap(text, max_chars):
    """Two readable lines at most, breaking near the middle."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return [text]
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= max_chars:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) <= 2:
        return lines
    # more than two lines: split evenly into two halves
    total = len(text)
    half = total // 2
    best, acc = None, 0
    for i, w in enumerate(words):
        acc += len(w) + 1
        if best is None or abs(acc - half) < abs(best[1] - half):
            best = (i, acc)
    cut = best[0] + 1
    return [" ".join(words[:cut]), " ".join(words[cut:])]


def load_wav(path):
    """Read the 16 kHz mono WAV into a float32 numpy array."""
    import wave
    import numpy as np
    with wave.open(path, "rb") as fh:
        frames = fh.readframes(fh.getnframes())
        width = fh.getsampwidth()
    if width == 2:
        data = np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0
    elif width == 4:
        data = np.frombuffer(frames, dtype="<i4").astype("float32") / 2147483648.0
    else:
        data = np.frombuffer(frames, dtype="<u1").astype("float32")
        data = (data - 128.0) / 128.0
    return data


def split_segment(seg, max_chars, max_gap=1.2, min_dur=0.9):
    """Split one whisper segment into subtitle-sized cues using word timings."""
    words = getattr(seg, "words", None)
    if not words:
        text = seg.text.strip()
        pieces = wrap(text, max_chars)
        if len(pieces) <= 1:
            return [(seg.start, seg.end, [text])]
        # no word timings: split the duration proportionally by characters
        total = sum(len(p) for p in pieces)
        out, t0, acc = [], seg.start, 0
        span = max(seg.end - seg.start, 0.5)
        for p in pieces:
            share = len(p) / total
            t1 = t0 + span * share
            out.append((t0, t1, [p]))
            t0 = t1
            acc += 1
        return out

    cues, cur, cur_start = [], [], None
    for w in words:
        word = w.word.strip()
        if not word:
            continue
        if cur_start is None:
            cur_start = w.start
        if cur and (w.start - cur[-1].end > max_gap):
            cues.append((cur_start, cur[-1].end, cur))
            cur, cur_start = [], w.start
        cur.append(w)
        joined = " ".join(x.word.strip() for x in cur)
        if len(joined) >= max_chars and w.end - cur_start >= min_dur:
            cues.append((cur_start, w.end, cur))
            cur, cur_start = [], None
    if cur:
        cues.append((cur_start, cur[-1].end, cur))
    return cues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--audio-stream", type=int, default=0)
    ap.add_argument("--language", default="en")
    ap.add_argument("--max-chars", type=int, default=42)
    ap.add_argument("--beam", type=int, default=5)
    args = ap.parse_args()

    cuda_libs()

    from faster_whisper import WhisperModel  # noqa: E402  (after libs are set)

    device, compute = "cuda", "float16"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() < 1:
            device, compute = "cpu", "int8"
    except Exception:
        device, compute = "cpu", "int8"
    if os.environ.get("ASR_CPU") == "1":
        device, compute = "cpu", "int8"
    print("device=%s compute=%s model=%s" % (device, compute, args.model), flush=True)

    wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    try:
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", args.input,
            "-map", "0:a:%d" % args.audio_stream,
            "-ac", "1", "-ar", "16000", "-vn", "-sn", "-dn",
            wav,
        ]
        print("extracting audio: %s" % wav, flush=True)
        subprocess.run(cmd, check=True)

        model = WhisperModel(args.model, device=device, compute_type=compute,
                             download_root=os.path.join(HERE, "models"))
        # Feed the samples directly: faster-whisper's own decoder goes through
        # PyAV, and the installed PyAV dropped the keyword it passes internally.
        audio = load_wav(wav)
        segments, info = model.transcribe(
            audio,
            language=args.language,
            task="transcribe",
            beam_size=args.beam,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 350,
                            "speech_pad_ms": 120},
            condition_on_previous_text=False,
            word_timestamps=True,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
        )
        total = max(float(getattr(info, "duration", 0.0) or 0.0), 1.0)
        cues = []
        for seg in segments:
            if seg.no_speech_prob and seg.no_speech_prob > 0.75:
                continue
            if not seg.text.strip():
                continue
            for start, end, words in split_segment(seg, args.max_chars):
                text = " ".join(w.word.strip() for w in words).strip()
                if not text:
                    continue
                lines = wrap(text, args.max_chars)
                cues.append((start, max(end, start + 0.4), lines))
            pct = min(99, int(seg.end / total * 100))
            print("PROGRESS %d" % pct, flush=True)
    finally:
        try:
            os.unlink(wav)
        except OSError:
            pass

    # tidy: merge absurdly short cues into the neighbour, drop empties
    fixed = []
    for i, (s, e, lines) in enumerate(cues):
        if fixed and e - s < 0.35 and len(lines) == 1 and len(lines[0]) < 4:
            continue
        fixed.append((s, e, lines))

    with open(args.output, "w", encoding="utf-8") as fh:
        for n, (s, e, lines) in enumerate(fixed, 1):
            fh.write("%d\n%s --> %s\n%s\n\n"
                     % (n, srt_time(s), srt_time(e), "\n".join(lines)))
    print("PROGRESS 100", flush=True)
    print("wrote %s (%d cues)" % (args.output, len(fixed)), flush=True)


if __name__ == "__main__":
    main()
