"""HandBrake / ffmpeg plumbing for the DVD Ripper.

No GTK in here on purpose: this module can be driven and tested from a plain
shell, which is how the encoder arguments and the split maths get verified.
"""

import json
import os
import re
import shutil
import subprocess
import time

HANDBRAKE = shutil.which("HandBrakeCLI") or "/usr/bin/HandBrakeCLI"
FFMPEG = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
# C0D3D (2026-11-12): "dont ever let anything run the cpu past 80%, always leave
# 20% reserve". HandBrake, ffmpeg and the transcriber all take every core by
# default, so their commands are pinned to the first 80% of this machine's CPUs
# and the desktop stays responsive while a rip runs.
def cpu_limit_prefix():
    """A `taskset` prefix that holds a job to 80% of the cores."""
    try:
        cores = sorted(os.sched_getaffinity(0))
    except AttributeError:  # pragma: no cover - non-Linux
        cores = list(range(os.cpu_count() or 1))
    if len(cores) < 2:
        return []
    limit = max(1, int(len(cores) * 4 / 5))
    taskset = shutil.which("taskset")
    if limit >= len(cores) or not taskset:
        return []
    return [taskset, "-c", ",".join(str(core) for core in cores[:limit])]



DIAG_DIR = os.path.expanduser("~/.local/state/ralph/diagnostics")
DIAG_LOG = os.path.join(DIAG_DIR, "dvd-ripper.log")

DEFAULT_OUTPUT_DIR = os.path.expanduser("~/Videos/DVD Rips")

# --------------------------------------------------------------------------
# quality presets.  `args` is spliced straight into the HandBrake command.
# --------------------------------------------------------------------------
PRESETS = [
    {
        "key": "best",
        "label": "Best — H.264 CRF 18 (MKV)",
        "short": "Best — H.264 CRF 18",
        "ext": "mkv",
        "note": "Archival quality, biggest files. Audio passed through untouched.",
        "args": ["-f", "av_mkv", "-e", "x264", "-q", "18",
                 "--encoder-preset", "slow", "--encoder-tune", "film"],
    },
    {
        "key": "balanced",
        "label": "Balanced — H.264 CRF 20 (MKV)",
        "short": "Balanced — H.264 CRF 20",
        "ext": "mkv",
        "note": "The sane default: visually identical to the disc at half the size.",
        "args": ["-f", "av_mkv", "-e", "x264", "-q", "20",
                 "--encoder-preset", "medium"],
    },
    {
        "key": "small",
        "label": "Small — H.264 CRF 23 (MP4)",
        "short": "Small — H.264 CRF 23 (MP4)",
        "ext": "mp4",
        "note": "Folder-friendly MP4 for players and phones.",
        "args": ["-f", "av_mp4", "-e", "x264", "-q", "23",
                 "--encoder-preset", "medium"],
    },
    {
        "key": "hevc",
        "label": "H.265 — CRF 22 (MKV)",
        "short": "H.265 — CRF 22 (MKV)",
        "ext": "mkv",
        "note": "About a third smaller than H.264, slower to encode.",
        "args": ["-f", "av_mkv", "-e", "x265", "-q", "22",
                 "--encoder-preset", "medium"],
    },
    {
        "key": "gpu",
        "label": "Fast — NVENC H.264 (MKV)",
        "short": "Fast — NVENC H.264",
        "ext": "mkv",
        "note": "GPU encode, several times faster, slightly larger files.",
        "args": ["-f", "av_mkv", "-e", "nvenc_h264", "-q", "22",
                 "--encoder-preset", "p5"],
    },
]

PRESET_BY_KEY = {preset["key"]: preset for preset in PRESETS}

AUDIO_MODES = [
    {"key": "copy", "label": "Passthrough — keep the disc audio",
     "short": "Passthrough (best)",
     "args": ["-E", "copy",
              "--audio-copy-mask", "ac3,eac3,dts,dtshd,truehd,aac,mp3,mp2,flac",
              "--audio-fallback", "av_aac"]},
    {"key": "copy_all",
     "label": "Every audio track, passed through untouched — dub and Japanese together",
     "short": "All tracks — passthrough",
     "args": ["--all-audio",
              "-E", "copy",
              "--audio-copy-mask", "ac3,eac3,dts,dtshd,truehd,aac,mp3,mp2,flac",
              "--audio-fallback", "av_aac"]},
    {"key": "aac192_all",
     "label": "Every audio track, re-encoded to AAC 192 kbps",
     "short": "All tracks — AAC 192k",
     "args": ["--all-audio", "-E", "av_aac", "-B", "192"]},
    {"key": "aac192", "label": "AAC 192 kbps — keep the surround mix",
     "short": "AAC 192k surround",
     "args": ["-E", "av_aac", "-B", "192"]},
    {"key": "aac128stereo", "label": "AAC 128 kbps stereo — smallest",
     "short": "AAC 128k stereo",
     "args": ["-E", "av_aac", "-B", "128", "-6", "stereo"]},
]

AUDIO_BY_KEY = {mode["key"]: mode for mode in AUDIO_MODES}

# which language tracks to pick out of the disc
AUDIO_LANGUAGES = [
    {"key": "any", "short": "Any — disc default", "langs": ""},
    {"key": "jpn_eng", "short": "Japanese first, then English", "langs": "jpn,eng"},
    {"key": "eng_jpn", "short": "English first, then Japanese", "langs": "eng,jpn"},
    {"key": "jpn", "short": "Japanese only", "langs": "jpn"},
    {"key": "eng", "short": "English only", "langs": "eng"},
    {"key": "fra", "short": "French only", "langs": "fra"},
    {"key": "deu", "short": "German only", "langs": "deu"},
    {"key": "spa", "short": "Spanish only", "langs": "spa"},
]

AUDIO_LANG_BY_KEY = {mode["key"]: mode for mode in AUDIO_LANGUAGES}

SUB_MODES = [
    {"key": "none", "label": "No subtitles", "short": "No subtitles",
     "args": ["-s", "none"]},
    {"key": "eng", "label": "English (default track)",
     "short": "English",
     "args": ["--subtitle-lang-list", "eng", "--first-subtitle"]},
    {"key": "jpn", "label": "Japanese (default track)",
     "short": "Japanese",
     "args": ["--subtitle-lang-list", "jpn", "--first-subtitle"]},
    {"key": "eng_jpn", "label": "English and Japanese",
     "short": "English + Japanese",
     "args": ["--subtitle-lang-list", "eng,jpn", "--all-subtitles"]},
    {"key": "all", "label": "Every subtitle track", "short": "Every track",
     "args": ["--all-subtitles"]},
]

SUB_BY_KEY = {mode["key"]: mode for mode in SUB_MODES}

DENOISE_MODES = [
    {"key": "off", "short": "Denoise: off", "value": None},
    {"key": "light", "short": "Denoise: light", "value": "light"},
    {"key": "medium", "short": "Denoise: medium", "value": "medium"},
    {"key": "strong", "short": "Denoise: strong", "value": "strong"},
]

DEBLOCK_MODES = [
    {"key": "off", "short": "Deblock: off", "value": None},
    {"key": "mild", "short": "Deblock: mild", "value": "1,1"},
    {"key": "strong", "short": "Deblock: strong", "value": "2,2"},
]

DENOISE_BY_KEY = {mode["key"]: mode for mode in DENOISE_MODES}
DEBLOCK_BY_KEY = {mode["key"]: mode for mode in DEBLOCK_MODES}

DEBAND_MODES = [
    {"key": "off", "short": "Deband: off", "value": None},
    {"key": "light", "short": "Deband: light (2nd pass)",
     "value": "deband=1thr=0.02:2thr=0.02:3thr=0.02:4thr=0.02:range=16"},
    {"key": "strong", "short": "Deband: strong (2nd pass)",
     "value": "deband=1thr=0.06:2thr=0.06:3thr=0.06:4thr=0.06:range=32:blur=1"},
]

DEBAND_BY_KEY = {mode["key"]: mode for mode in DEBAND_MODES}

RESOLUTIONS = [
    {"key": "native", "short": "Keep disc resolution (best)", "height": 0},
    {"key": "720", "short": "Upscale to 720p", "height": 720},
    {"key": "1080", "short": "Upscale to 1080p", "height": 1080},
    {"key": "2160", "short": "Upscale to 4K (2160p)", "height": 2160},
]

RESOLUTION_BY_KEY = {mode["key"]: mode for mode in RESOLUTIONS}

TIME_RE = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def log(message):
    try:
        os.makedirs(DIAG_DIR, exist_ok=True)
        with open(DIAG_LOG, "a", encoding="utf-8") as handle:
            handle.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except OSError:
        pass


def fmt_hms(seconds):
    """1:02:03 / 2:03 — for durations."""
    seconds = max(0, int(round(float(seconds or 0))))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    return "%d:%02d" % (minutes, secs)


def fmt_clock(seconds):
    """00:01:02 — for timestamps handed back to HandBrake."""
    seconds = max(0, int(round(float(seconds or 0))))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return "%02d:%02d:%02d" % (hours, minutes, secs)


def tc_to_seconds(text):
    parts = [int(piece) for piece in text.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def fmt_bytes(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return "%.1f %s" % (value, unit) if unit != "B" else "%d B" % value
        value /= 1024
    return "%.1f TB" % value


def safe_filename(text, fallback="Title"):
    cleaned = re.sub(r"[^\w\s.\-()&']", "", str(text or "")).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or fallback


# --------------------------------------------------------------------------
# titles
# --------------------------------------------------------------------------
class Title:
    """One title (a VTS playlist) on the disc."""

    def __init__(self, raw):
        self.number = int(raw.get("Index") or 0)
        self.raw = raw
        duration = raw.get("Duration") or {}
        self.duration = (duration.get("Hours", 0) * 3600
                         + duration.get("Minutes", 0) * 60
                         + duration.get("Seconds", 0))
        geometry = raw.get("Geometry") or {}
        self.width = int(geometry.get("Width") or 0)
        self.height = int(geometry.get("Height") or 0)
        par = geometry.get("PAR") or {}
        try:
            self.par = (float(par.get("Num") or 1) / float(par.get("Den") or 1))
        except (TypeError, ValueError, ZeroDivisionError):
            self.par = 1.0
        self.name = (raw.get("Name") or "").strip()
        self.chapters = []
        for chapter in raw.get("ChapterList") or []:
            length = chapter.get("Duration") or {}
            self.chapters.append(length.get("Hours", 0) * 3600
                                 + length.get("Minutes", 0) * 60
                                 + length.get("Seconds", 0))
        self.audio = raw.get("AudioList") or []
        self.subtitles = raw.get("SubtitleList") or []

    @property
    def chapter_starts(self):
        starts, running = [], 0.0
        for length in self.chapters:
            starts.append(running)
            running += length
        return starts

    @property
    def main_audio(self):
        for track in self.audio:
            if (track.get("Attributes") or {}).get("Default"):
                return track
        return self.audio[0] if self.audio else {}

    def size_estimate(self, preset_key="balanced"):
        """Rough bitrate maths so the list has a size next to it."""
        rates = {"best": 2200, "balanced": 1500, "small": 900,
                 "hevc": 1100, "gpu": 1800}
        return self.duration * rates.get(preset_key, 1500) * 1000 / 8

    def summary(self):
        audio = self.main_audio
        channels = audio.get("ChannelLayout") or ""
        codec = (audio.get("CodecName") or "").upper()
        bits = []
        if self.width and self.height:
            bits.append("%dx%d" % (self.width, self.height))
        bits.append(fmt_hms(self.duration))
        if self.chapters:
            bits.append("%d chapters" % len(self.chapters))
        if codec:
            bits.append(("%s %s" % (codec, channels)).strip())
        if self.subtitles:
            bits.append("%d sub%s" % (len(self.subtitles),
                                      "" if len(self.subtitles) == 1 else "s"))
        return " · ".join(bits)


def parse_scan(text):
    """Pull the JSON Title Set out of `HandBrakeCLI --json --scan` output."""
    marker = "JSON Title Set:"
    index = text.find(marker)
    if index < 0:
        return None
    blob = text[index + len(marker):].strip()
    start = blob.find("{")
    if start < 0:
        return None
    blob = blob[start:]
    # hand back the last complete top-level object
    depth = 0
    end = None
    in_string = False
    escaped = False
    for position, character in enumerate(blob):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                end = position + 1
                break
    if end is None:
        return None
    try:
        data = json.loads(blob[:end])
    except json.JSONDecodeError as error:
        log("scan json error: %s" % error)
        return None
    titles = [Title(raw) for raw in data.get("TitleList") or []]
    main = int(data.get("MainFeature") or 0)
    return {"main": main, "titles": titles}


def scan_command(source, min_duration=10):
    return cpu_limit_prefix() + [
        HANDBRAKE, "--json", "-i", source, "-t", "0", "--scan",
        "--min-duration", str(min_duration)]


def list_sources():
    """Optical drives that exist right now (USB readers land on /dev/sr*)."""
    found = []
    for name in ("sr0", "sr1", "sr2", "sr3"):
        path = "/dev/" + name
        if os.path.exists(path):
            found.append(path)
    for alias in ("/dev/cdrom", "/dev/dvd", "/dev/cdrw"):
        if os.path.exists(alias):
            real = os.path.realpath(alias)
            if real not in found and os.path.basename(real).startswith("sr"):
                found.append(real)
    return found


# --------------------------------------------------------------------------
# job building
# --------------------------------------------------------------------------
def target_size(title, resolution_key):
    """Pixel size for an upscale, keeping the disc's display shape."""
    height = RESOLUTION_BY_KEY.get(resolution_key, {}).get("height", 0)
    if not height or not title or not title.width or not title.height:
        return None
    aspect = (title.width * (title.par or 1.0)) / float(title.height)
    width = int(round(height * aspect / 2.0)) * 2
    return width, height


def build_encode_command(source, title_number, output_path, preset_key,
                         audio_key, sub_key, start=None, stop=None,
                         chapters=None, audio_lang="any", markers=True,
                         size=None, anime=False, denoise="off", deblock="off"):
    preset = PRESET_BY_KEY.get(preset_key, PRESET_BY_KEY["balanced"])
    audio = AUDIO_BY_KEY.get(audio_key, AUDIO_BY_KEY["copy"])
    subs = SUB_BY_KEY.get(sub_key, SUB_BY_KEY["none"])
    language = AUDIO_LANG_BY_KEY.get(audio_lang, AUDIO_LANG_BY_KEY["any"])

    command = cpu_limit_prefix() + [
        HANDBRAKE, "--json", "-i", source, "-t", str(title_number),
        "-o", output_path]
    preset_args = list(preset["args"])
    if anime:
        # x264/x265 tune for line art; replaces whatever tune the preset set
        cleaned = []
        skip = False
        for item in preset_args:
            if skip:
                skip = False
                continue
            if item == "--encoder-tune":
                skip = True
                continue
            cleaned.append(item)
        preset_args = cleaned
        encoder_name = ""
        for index, item in enumerate(preset_args):
            if item in ("-e", "--encoder") and index + 1 < len(preset_args):
                encoder_name = preset_args[index + 1]
        if encoder_name.startswith("nvenc"):
            preset_args += ["--encoder-tune", "hq"]        # nvenc has no x264 tunes
        elif encoder_name.startswith(("x264", "x265")):
            preset_args += ["--encoder-tune", "animation"]
    command += preset_args

    denoise_value = DENOISE_BY_KEY.get(denoise, {}).get("value")
    if denoise_value:
        command += ["--hqdn3d=%s" % denoise_value]

    deblock_value = DEBLOCK_BY_KEY.get(deblock, {}).get("value")
    encoder = preset.get("args", [])
    software = ("x264" in encoder or "x265" in encoder)
    if deblock_value and software:
        command += ["-x", "deblock=%s" % deblock_value]
    command += list(audio["args"])
    if language.get("langs"):
        command += ["--audio-lang-list", language["langs"]]
        # match the language filter to how many tracks we asked for
        if "--all-audio" not in audio["args"]:
            command += ["--first-audio"]
    command += list(subs["args"])
    command += ["--decomb", "--crop-mode", "auto"]
    if chapters:
        command += ["-c", str(chapters)]
    if size:
        command += ["--width", str(size[0]), "--height", str(size[1]),
                    "--non-anamorphic"]
    if not markers:
        # HandBrake writes chapter markers by default; this strips them
        command += ["--no-markers"]
    if start is not None:
        command += ["--start-at", "seconds:%d" % int(start)]
        if stop is not None:
            command += ["--stop-at", "seconds:%d" % int(max(1, stop - start))]
    return command


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".ts", ".m2ts", ".webm",
                    ".mov", ".mpg", ".mpeg", ".wmv", ".flv", ".ogv"}


def is_video_file(path):
    """A plain video file (already ripped) rather than a disc or an ISO."""
    return os.path.splitext(str(path or ""))[1].lower() in VIDEO_EXTENSIONS


def build_copy_command(source, output_path, start, stop):
    """Lossless split: stream copy, no re-encode, cuts at the nearest keyframe."""
    duration = max(0.5, float(stop) - float(start))
    return cpu_limit_prefix() + [
        FFMPEG, "-hide_banner", "-nostdin", "-y",
        "-ss", "%.3f" % float(start),
            "-i", source,
            "-t", "%.3f" % duration,
            "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero",
            "-progress", "pipe:1", "-nostats",
            output_path]


def parse_copy_progress(line):
    """ffmpeg -progress lines -> seconds of output written (or None)."""
    line = line.strip()
    if line.startswith("out_time="):
        value = line.split("=", 1)[1]
        parts = value.split(":")
        try:
            seconds = (float(parts[0]) * 3600 + float(parts[1]) * 60
                       + float(parts[2])) if len(parts) == 3 else float(value)
        except (ValueError, IndexError):
            return None
        if seconds < 0:
            return None
        return seconds
    return None


def chapter_span(title, chapters):
    """'3-5' -> (start seconds, stop seconds) using the scanned chapter list."""
    low, _, high = str(chapters).partition("-")
    try:
        first = max(1, int(low))
        last = int(high) if high else first
    except ValueError:
        return None
    starts = title.chapter_starts
    if not starts:
        return None
    first = min(first, len(starts))
    last = min(max(last, first), len(starts))
    start = starts[first - 1]
    stop = starts[last] if last < len(starts) else title.duration
    return start, stop


def parse_chapter_ranges(text, chapter_count):
    """'1-4, 6, 8-10' -> [(1,4), (6,6), (8,10)], clamped to the title."""
    ranges = []
    for chunk in re.split(r"[,\s]+", str(text or "")):
        if not chunk:
            continue
        if "-" in chunk:
            left, _, right = chunk.partition("-")
            try:
                low, high = int(left), int(right)
            except ValueError:
                continue
        else:
            try:
                low = high = int(chunk)
            except ValueError:
                continue
        low = max(1, min(low, chapter_count))
        high = max(1, min(high, chapter_count))
        if high < low:
            low, high = high, low
        ranges.append((low, high))
    return ranges


def parse_timestamp_segments(text):
    """One line per file:  `00:22:10-00:44:30 name`  /  `00:22:10 name`."""
    segments = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        stamps = TIME_RE.findall(line)
        if not stamps:
            continue
        start = tc_to_seconds(stamps[0])
        end = tc_to_seconds(stamps[1]) if len(stamps) > 1 else None
        name = line
        for stamp in stamps[:2]:
            name = name.replace(stamp, " ", 1)
        name = re.sub(r"[|\-–—,]+", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        segments.append({"start": start, "end": end, "name": name})
    segments.sort(key=lambda item: item["start"])
    return segments


def segment_jobs(title, mode, text, base_name, chapter_ranges_text=""):
    """Turn the split settings into a list of (label, start, stop, chapters).

    Whole title -> one job.  Chapters -> one job per range (encoded directly by
    HandBrake so each file starts exactly on a chapter).  Timestamps -> one job
    per line with --start-at/--stop-at, again a real encode of just that span.
    """
    if mode == "whole":
        return [{"label": base_name, "start": None, "stop": None,
                 "chapters": None}]

    jobs = []
    if mode == "chapters":
        ranges = parse_chapter_ranges(chapter_ranges_text or text,
                                      max(1, len(title.chapters) or 1))
        for number, (low, high) in enumerate(ranges, start=1):
            label = "%s - Ch %d" % (base_name, low) if low == high else \
                    "%s - Ch %d-%d" % (base_name, low, high)
            jobs.append({"label": label, "start": None, "stop": None,
                         "chapters": "%d-%d" % (low, high)})
        return jobs

    starts = title.chapter_starts
    for number, segment in enumerate(parse_timestamp_segments(text), start=1):
        name = segment["name"] or ("Part %02d" % number)
        jobs.append({
            "label": "%s - %s" % (base_name, name),
            "start": segment["start"],
            "stop": segment["end"],
            "chapters": None,
            "suffix_hint": fmt_clock(segment["start"]),
            "chapter_hint": chapter_index_at(starts, segment["start"]),
        })
    return jobs


def chapter_index_at(starts, moment):
    index = 0
    for position, start in enumerate(starts):
        if start <= moment + 0.5:
            index = position
    return index + 1 if starts else 0


def chapter_boundaries(title):
    """'00:00:00 1', '00:07:31 2' … for the hint list in the UI."""
    return [{"number": number, "start": start, "time": fmt_clock(start)}
            for number, start in enumerate(title.chapter_starts, start=1)]


# --------------------------------------------------------------------------
# progress parsing
# --------------------------------------------------------------------------
class JsonStreamParser:
    """Feed stdout lines in, get dicts back for each `Label: { … }` block."""

    def __init__(self, callback):
        self.callback = callback
        self.label = None
        self.buffer = []

    def feed(self, line):
        stripped = line.rstrip("\n")
        if self.label is None:
            match = re.match(r"^(Version|JSON Title Set|Progress|Preview|Scan):\s*(\{.*)$",
                             stripped)
            if match:
                self.label = match.group(1)
                self.buffer = [match.group(2)]
            return
        self.buffer.append(stripped)
        blob = "\n".join(self.buffer)
        try:
            payload = json.loads(blob)
        except json.JSONDecodeError:
            return
        label, self.label, self.buffer = self.label, None, []
        self.callback(label, payload)


def progress_values(payload):
    """Normalise a Progress block into plain numbers."""
    state = payload.get("State") or ""
    working = payload.get("Working") or {}
    if state == "WORKDONE":
        return {"state": "done",
                "error": (payload.get("WorkDone") or {}).get("Error", 0)}
    if state == "SCANNING":
        scanning = payload.get("Scanning") or {}
        total = scanning.get("TitleCount") or 0
        current = scanning.get("TitleIndex") or 0
        return {"state": "scanning", "title": current, "total": total}
    if state == "WORKING":
        progress = float(working.get("Progress") or 0.0)
        return {
            "state": "working",
            "fraction": max(0.0, min(1.0, progress)),
            "eta": working.get("ETASeconds") or 0,
            "rate": working.get("Rate") or 0.0,
            "rate_avg": working.get("RateAvg") or 0.0,
            "pass": working.get("Pass") or 1,
            "pass_count": working.get("PassCount") or 1,
        }
    return {"state": state.lower() or "unknown"}


# --------------------------------------------------------------------------
# finding the episode breaks inside one long title
# --------------------------------------------------------------------------
SILENCE_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")
BLACK_RE = re.compile(r"black_start:(\d+(?:\.\d+)?)\s+black_end:(\d+(?:\.\d+)?)")


def detect_command(path, noise_db=-35.0, silence_seconds=0.8):
    """ffmpeg analyses the audio for gaps and the picture for black stretches."""
    return cpu_limit_prefix() + [
        FFMPEG, "-hide_banner", "-nostdin", "-i", path,
        "-map", "0:a:0", "-af",
            "silencedetect=noise=%sdB:d=%s" % (noise_db, silence_seconds),
            "-f", "null", "-"]


def detect_black_command(path):
    return cpu_limit_prefix() + [
        FFMPEG, "-hide_banner", "-nostdin", "-i", path,
        "-map", "0:v:0", "-vf", "blackdetect=d=0.5:pix_th=0.10",
            "-f", "null", "-"]


def parse_break_times(text):
    """Gaps + black stretches -> candidate timestamps (seconds)."""
    points = []
    for match in SILENCE_RE.finditer(text):
        try:
            points.append(float(match.group(1)))
        except ValueError:
            continue
    for match in BLACK_RE.finditer(text):
        try:
            points.append(float(match.group(1)))
            points.append(float(match.group(2)))
        except ValueError:
            continue
    return sorted(points)


def find_breaks(path, duration, parts):
    """Analyse a video file and return (candidate points, chosen breaks).

    Two passes: the audio, for the silence where an episode ends and the next
    begins, and the picture, for the black stretch between them. Both are needed
    because a disc may cut on black with music over it, or on silence with the
    picture still going.
    """
    points = []
    for command in (detect_command(path), detect_black_command(path)):
        result = subprocess.run(command, capture_output=True, text=True,
                                check=False)
        points.extend(parse_break_times(result.stderr or ""))
    points = sorted({round(point, 2) for point in points if point > 0})
    return points, choose_breaks(points, parts, duration)


def choose_breaks(points, parts, duration):
    """Pick parts-1 breaks closest to an even division of the title."""
    if parts < 2 or not duration:
        return []
    targets = [duration * index / parts for index in range(1, parts)]
    remaining = list(points)
    picked = []
    for target in targets:
        if not remaining:
            picked.append(target)
            continue
        best = min(remaining, key=lambda value: abs(value - target))
        if abs(best - target) > max(45.0, duration / parts / 3.0):
            picked.append(target)      # nothing convincing near there
        else:
            remaining.remove(best)
            picked.append(best)
    return picked


def segments_from_breaks(breaks, duration):
    edges = [0.0] + [max(0.0, min(duration, value)) for value in breaks] + [duration]
    out = []
    for index in range(len(edges) - 1):
        start, stop = edges[index], edges[index + 1]
        if stop - start < 5:
            continue
        out.append({"start": start, "stop": stop})
    return out


def best_episode_count(title, candidates=tuple(range(2, 9)), tolerance=45.0):
    """How many episodes are inside one long title?

    A play-all playlist keeps the episodes' chapter marks, so the episode
    breaks show up as chapter starts sitting right where an even division
    falls. Score each candidate count by how close the nearest chapter is to
    each division and take the best fit.
    """
    if not title or not title.duration or len(title.chapters) < 2:
        return None
    starts = [value for value in title.chapter_starts if 0.0 < value < title.duration]
    if not starts:
        return None
    scored = []
    for count in candidates:
        targets = [title.duration * index / count for index in range(1, count)]
        errors = [min(abs(start - target) for start in starts) for target in targets]
        if all(error <= tolerance for error in errors):
            scored.append((sum(errors) / len(errors), -count, count))
    if not scored:
        return None
    scored.sort()
    return scored[0][2]


def deband_command(source_path, output_path, mode_key, quality=18):
    """Second pass: ffmpeg's deband over the finished file (re-encodes the video)."""
    mode = DEBAND_BY_KEY.get(mode_key, {})
    filter_spec = mode.get("value")
    if not filter_spec:
        return None
    return cpu_limit_prefix() + [
        FFMPEG, "-hide_banner", "-nostdin", "-y",
        "-i", source_path,
        "-map", "0", "-c:v", "libx264", "-crf", str(quality),
            "-preset", "medium", "-vf", filter_spec,
            "-c:a", "copy", "-c:s", "copy",
            "-map_metadata", "0", "-map_chapters", "0",
            "-progress", "pipe:1", "-nostats",
            output_path]


# --- Transcript (speech-to-text of the English audio) -----------------------
# C0D3D (2026-11-11): the disc's English subtitles are a translation of the
# Japanese script, so they say something different from the English dub. The
# transcript pass listens to the dub that is actually in the file and writes
# subtitles from it, so the words match what is being said.

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASR_DIR = os.path.join(APP_DIR, "asr")
ASR_PYTHON = os.path.join(ASR_DIR, "venv", "bin", "python")
ASR_SCRIPT = os.path.join(ASR_DIR, "transcribe.py")

TRANSCRIPT_MODES = [
    {"key": "off", "short": "Transcript: off", "model": None},
    {"key": "fast", "short": "Transcript: fast", "model": "small.en"},
    {"key": "better", "short": "Transcript: better", "model": "medium.en"},
    {"key": "best", "short": "Transcript: best", "model": "large-v3-turbo"},
]

TRANSCRIPT_BY_KEY = {mode["key"]: mode for mode in TRANSCRIPT_MODES}


def asr_available():
    return os.path.isfile(ASR_PYTHON) and os.path.isfile(ASR_SCRIPT)


def transcript_command(video_path, srt_path, model, audio_stream=0):
    """Speech-to-text over one audio stream, writing an SRT beside the video."""
    return cpu_limit_prefix() + [
        ASR_PYTHON, ASR_SCRIPT,
        "--input", video_path,
            "--output", srt_path,
            "--model", model,
            "--audio-stream", str(audio_stream),
            "--max-chars", "42"]


def parse_transcript_progress(line):
    """Return the percent from a "PROGRESS 42" line, else None."""
    text = (line or "").strip()
    if not text.startswith("PROGRESS "):
        return None
    try:
        return max(0, min(100, int(text.split(None, 1)[1])))
    except (IndexError, ValueError):
        return None


def mux_transcript_command(video_path, srt_path, output_path, keep_disc=True):
    """Put the transcript into the file as the default English subtitle track.

    The transcript is always mapped first, so it is stream 0 no matter how many
    disc subtitle tracks the rip carried. keep_disc=True keeps the disc's
    translation as an extra track; False drops it entirely.
    """
    command = cpu_limit_prefix() + [
        FFMPEG, "-hide_banner", "-nostdin", "-y",
        "-i", video_path, "-i", srt_path,
               "-map", "0:v", "-map", "0:a", "-map", "1:0"]
    if keep_disc:
        command += ["-map", "0:s?", "-c:s", "copy", "-c:s:0", "srt"]
    else:
        command += ["-c:s", "srt"]
    command += [
        "-c:v", "copy", "-c:a", "copy",
        "-metadata:s:s:0", "language=eng",
        "-metadata:s:s:0", "title=English (transcript)",
        "-disposition:s:0", "default",
        "-map_metadata", "0", "-map_chapters", "0",
        output_path,
    ]
    return command
