"""Episode-name lookup for the DVD Ripper (FileBot-ish, no API key needed).

Uses the TVmaze public API — free, no auth, returns a show's whole episode
list in one call. Results are cached on disk so a disc can be ripped offline
after it has been looked up once.
"""

import difflib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

CACHE_PATH = os.path.expanduser(
    "~/.local/share/c0d3d/dvd-ripper/episode-cache.json")
CACHE_TTL = 7 * 24 * 3600          # a week; names do not change
USER_AGENT = "DVD-Ripper/1.0 (local desktop tool)"
TIMEOUT = 12

STYLE_SEASON = "season"            # Bleach - S01E057 - Title
STYLE_ABSOLUTE = "absolute"        # Bleach - 057 - Title

STYLES = [
    {"key": STYLE_SEASON, "short": "S01E03 style",
     "label": "Show - S01E03 - Episode title"},
    {"key": STYLE_ABSOLUTE, "short": "057 style",
     "label": "Show - 057 - Episode title (absolute numbering)"},
]


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------
def _load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        temp = CACHE_PATH + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(cache, handle, indent=1)
        os.replace(temp, CACHE_PATH)
    except OSError:
        pass


def _fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


# --------------------------------------------------------------------------
# lookup
# --------------------------------------------------------------------------
# disc labels carry marketing words that no show is actually called
NOISE_WORDS = {
    "uncut", "unrated", "uncensored", "complete", "season", "seasons",
    "vol", "volume", "disc", "disk", "dvd", "bluray", "blu", "ray",
    "box", "set", "collection", "remastered", "edition", "the", "series",
}


def tidy_query(query):
    """'Bleach Uncut' -> 'Bleach'; drops disc-label words and stray numbers."""
    words = [word for word in re.split(r"\s+", str(query or "").strip()) if word]
    while words and (words[-1].lower() in NOISE_WORDS
                     or words[-1].isdigit()):
        words.pop()
    return " ".join(words)


def _search_api(query):
    url = ("https://api.tvmaze.com/search/shows?q="
           + urllib.parse.quote(query))
    try:
        return _fetch(url) or []
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return []


def _collect(query):
    """Search, dropping words off the end until something comes back."""
    wanted = tidy_query(query) or str(query or "").strip()
    if not wanted:
        return []
    rows = _search_api(wanted)
    attempt = wanted
    while not rows and " " in attempt:
        attempt = attempt.rsplit(" ", 1)[0].strip()
        if attempt:
            rows = _search_api(attempt)
    return rows


def search(query):
    """Find shows by name, tolerant of 'Bleach Uncut' style disc labels."""
    query = str(query or "").strip()
    if not query:
        return []
    cache = _load_cache()
    key = "search:" + query.lower()
    hit = cache.get(key)
    if hit and time.time() - hit.get("at", 0) < CACHE_TTL:
        return hit["shows"]

    payload = _collect(query)
    if not payload:
        return hit["shows"] if hit else []

    wanted = (tidy_query(query) or query).lower()
    shows, seen = [], set()
    for row in payload:
        show = row.get("show") or {}
        show_id = show.get("id")
        if not show_id or show_id in seen:
            continue
        seen.add(show_id)
        name = show.get("name") or "Unknown"
        # how close the result is to what he typed, best first
        ratio = difflib.SequenceMatcher(
            None, wanted, name.lower()).ratio()
        shows.append({
            "id": show_id,
            "name": name,
            "premiered": show.get("premiered") or "",
            "runtime": show.get("averageRuntime") or show.get("runtime") or 0,
            "country": ((show.get("network") or show.get("webChannel") or {})
                        .get("country") or {}).get("code", ""),
            "score": round(ratio, 3),
        })
    shows.sort(key=lambda item: (-item["score"], item["name"]))
    cache[key] = {"at": time.time(), "shows": shows}
    _save_cache(cache)
    return shows


def clean_title(text):
    """Episode titles can carry HTML; flatten and trim."""
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def episodes(show_id):
    """Every episode of a show in broadcast order."""
    cache = _load_cache()
    key = "show:%s" % show_id
    hit = cache.get(key)
    if hit and time.time() - hit.get("at", 0) < CACHE_TTL:
        return hit["episodes"]
    url = "https://api.tvmaze.com/shows/%s/episodes" % urllib.parse.quote(
        str(show_id))
    try:
        payload = _fetch(url)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return hit["episodes"] if hit else []
    rows = []
    for row in payload or []:
        rows.append({
            "season": row.get("season"),
            "number": row.get("number"),
            "name": clean_title(row.get("name")),
            "airdate": row.get("airdate") or "",
        })
    cache[key] = {"at": time.time(), "episodes": rows}
    _save_cache(cache)
    return rows


def season_options(rows):
    """Distinct seasons, in order ('Any' handled by the caller)."""
    seen = []
    for row in rows:
        season = row.get("season")
        if season is None or season in seen:
            continue
        seen.append(season)
    return seen


def ordered(rows):
    """Broadcast order, with each episode's absolute position attached."""
    cleaned = [dict(row) for row in rows if row.get("number") is not None]
    cleaned.sort(key=lambda row: (int(row.get("season") or 0),
                                  int(row.get("number") or 0)))
    for position, row in enumerate(cleaned, start=1):
        row["index"] = position
    return cleaned


def pick(rows, season, start, count, style=STYLE_SEASON):
    """Choose `count` episodes from an absolute position or a season number.

    TVmaze files long-running anime under year-seasons (Bleach: 2004, 2005 …)
    with the episode number restarting every year, so absolute numbering works
    off the position in the full broadcast order instead of `number`.
    """
    if not rows or count <= 0:
        return []
    start = max(1, int(start or 1))
    pool = ordered(rows)
    seasonless = season in (None, "", "any")
    if style == STYLE_ABSOLUTE or seasonless:
        return [row for row in pool if row["index"] >= start][:count]
    try:
        wanted = int(season)
    except (TypeError, ValueError):
        return [row for row in pool if row["index"] >= start][:count]
    inside = [row for row in pool
              if int(row.get("season") or 0) == wanted
              and int(row.get("number") or 0) >= start]
    if inside:
        return inside[:count]
    # nothing that high in that season: fall back to broadcast order
    return [row for row in pool if row["index"] >= start][:count]


def label(show_name, row, style, season_for_name=None):
    """'Bleach - S01E057 - Title' or 'Bleach - 057 - Title'."""
    number = int(row.get("number") or 0)
    title = row.get("name") or ""
    if style == STYLE_ABSOLUTE:
        stem = "%s - %03d" % (show_name, int(row.get("index") or number))
    else:
        season = season_for_name if season_for_name not in (None, "", "any") \
            else row.get("season")
        try:
            season = int(season)
        except (TypeError, ValueError):
            season = 1
        stem = "%s - S%02dE%02d" % (show_name, season, number)
    if title:
        stem += " - " + title
    return stem


# --------------------------------------------------------------------------
# disc labels ("BLEACH_DISC_03", "BLEACH V3", "BLEACH_DVD_2")
# --------------------------------------------------------------------------
DISC_PATTERNS = [
    re.compile(r"\bDISC[\s._-]*0*(\d{1,3})\b", re.I),
    re.compile(r"\bDISK[\s._-]*0*(\d{1,3})\b", re.I),
    re.compile(r"\bVOL(?:UME)?[\s._-]*0*(\d{1,3})\b", re.I),
    re.compile(r"\bDVD[\s._-]*0*(\d{1,3})\b", re.I),
    re.compile(r"\bD0*(\d{1,3})\b", re.I),
    re.compile(r"\bV0*(\d{1,3})\b", re.I),
]


def disc_number(label):
    """Pull the disc/volume number out of a disc's volume label, if it has one."""
    text = str(label or "").strip()
    if not text:
        return None
    text = text.replace("_", " ").replace("-", " ")
    for pattern in DISC_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                number = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if 1 <= number <= 200:
                return number
    return None
