"""Search YouTube and rank results so the OFFICIAL upload of an "artist + track"
query surfaces as #1.

yt_dlp's ``ytsearch`` returns YouTube-relevance order — usually decent, but it
puts covers, lyric videos, live cuts, and remixes in front of the official
upload far too often. For a grinder the operator types "Radiohead Karma Police"
expecting the studio track, not a fan cover with 312 views. This module
re-ranks against that intent.

Ranking signals (composite, higher = better):
  - title similarity to the canonical "{artist} - {title}" form (difflib ratio)
  - channel is the artist's "Topic" / VEVO / OAC (the canonical official upload)
  - duration in the 2:00–6:00 band (typical song length); outliers demoted
  - negative keywords in title demoted (cover / remix / live / reaction / …)
    UNLESS the query itself contained them (so "karma police live" is honoured)
  - view_count on a log scale (weak tiebreaker)
  - YouTube's original rank (weak tiebreaker — stable on relevance for ties)

All stdlib — runs on the grainneukeln venv python (no numpy dependency here).
"""

import math
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse, parse_qs

import yt_dlp

DEFAULT_N = 12

# Negative-keyword demotion. Each match pushes the result down. The query
# itself opts out: if the user typed "karma police live", "live" is NOT a
# negative — it is what they asked for.
NEGATIVE_KEYWORDS = (
    "cover", "covers",
    "remix", "remixes", "remixed",
    "live", "acoustic",
    "reaction", "reacts",
    "instrumental", "karaoke",
    "8d", "slowed", "sped up", "reverb",
    "mashup", "mash up",
    "tutorial", "guitar lesson", "piano tutorial",
    "teaser", "snippet", "preview",
    "lyric video", "lyrics video", "with lyrics", "lyrics",
)

# Heavier penalties for the most-misleading words (a "cover" or "remix" is almost
# never what the operator meant by "artist + track").
HEAVY_NEGATIVE = frozenset(("cover", "covers", "remix", "remixes", "remixed",
                            "reaction", "reacts", "mashup"))
MEDIUM_NEGATIVE = frozenset(("live", "acoustic", "instrumental", "karaoke",
                             "lyric video", "lyrics video", "with lyrics", "lyrics"))

# Audio extensions — used by the TUI/CLI to detect "this is a local file, not a query".
AUDIO_EXTS = ("wav", "mp3", "flac", "ogg", "m4a", "aac", "opus", "wma", "aiff", "aif")


# ─── input classification ──────────────────────────────────────────────────────

def is_url(value):
    v = (value or "").strip()
    return v.startswith("http://") or v.startswith("https://")


def is_local_path(value):
    """A local file path. Conservative: only returns True for things that look
    unambiguously like a path (so "Radiohead Karma Police" is treated as a query,
    not a file)."""
    v = (value or "").strip()
    if not v:
        return False
    if v.startswith(("/", "./", "../", "~/")):
        return True
    low = v.lower()
    return any(low.endswith("." + ext) for ext in AUDIO_EXTS)


# ─── query parsing ────────────────────────────────────────────────────────────

def parse_query(q):
    """Split a free-text query into ``(artist, title)``. Either may be None.

    Recognized separators (in priority order):
        ``" - "``   the canonical YouTube title form  ("Artist - Track")
        ``" – "`` | ``" — "`` | ``" − "``  en/em/minus dash variants pasted from titles
        ``" + "`` | ``"+"``   operator form  ("radiohead+karma police")
        ``" by "``  reversed   ("karma police by radiohead")

    If no separator matches, returns ``(None, q)`` — the whole string is treated
    as the title match target, and no channel-artist match is attempted.
    """
    q = re.sub(r"\s+", " ", (q or "").strip())
    if not q:
        return None, None

    for sep in (" - ", " – ", " — ", " − "):
        if sep in q:
            head, _, tail = q.partition(sep)
            return head.strip(), tail.strip() or None

    if " + " in q:
        head, _, tail = q.partition(" + ")
        return head.strip(), tail.strip() or None
    if "+" in q and " " not in q.split("+", 1)[0]:
        head, _, tail = q.partition("+")
        return head.strip(), tail.strip() or None

    m = re.search(r"\s+by\s+", q)
    if m:
        return q[m.end():].strip(), q[:m.start()].strip()

    return None, q


# ─── similarity helpers ───────────────────────────────────────────────────────

def _norm(s):
    """Lowercase, collapse non-alphanumerics to single spaces. For fuzzy matching."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _similarity(a, b):
    """0..1 — how close two normalized strings are."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# ─── per-axis scores ──────────────────────────────────────────────────────────

def _title_score(entry_title, artist, title):
    """How well the entry's title matches the canonical "{artist} - {title}"."""
    if not title:
        return 0.4   # nothing to match against — neutral-low
    canonical = f"{artist} - {title}" if artist else title
    direct = _similarity(entry_title, canonical)
    # Some official uploads are "Artist - Title (Official Audio)" (high direct
    # ratio) but Topic-channel ones are often just "Title". Score against the
    # title alone too and take the max, so a bare title on a Topic channel still
    # scores well.
    title_only = _similarity(entry_title, title)
    return max(direct, 0.75 * title_only)


def _channel_score(entry, artist):
    """Strong signal: is this the artist's OWN channel?

    YouTube auto-generates ``<Artist> - Topic`` channels for officially-licensed
    music; the upload there IS the canonical studio recording. VEVO and OACs
    (Official Artist Channels) are the other two authoritative sources.
    """
    if not artist:
        return 0.0
    chan = _norm(entry.get("channel") or "")
    upl = _norm(entry.get("uploader") or "")
    a = _norm(artist)
    a_nospace = a.replace(" ", "")

    # Official auto-generated topic channel: "<Artist> - Topic".
    if chan.endswith(" topic") and chan.startswith(a + " "):
        return 1.0
    if chan == a + " topic":
        return 1.0
    # VEVO channels: "<Artist>VEVO".
    if chan.endswith("vevo") and chan.startswith(a_nospace):
        return 0.95
    if upl.endswith("vevo") and upl.startswith(a_nospace):
        return 0.95
    # Exact artist match on channel/uploader.
    if chan == a or upl == a:
        return 0.9
    # Artist is a leading token of the channel ("RadioheadOfficial" → "radiohead").
    if a:
        tokens = chan.split() + upl.split()
        if any(t == a for t in tokens):
            return 0.55
        if a in chan or a in upl:
            return 0.35
    return 0.0


def _duration_score(duration):
    """Favor the 2:00–6:00 band; demote extremes (likely shorts/previews or mixes)."""
    if duration is None:
        # Topic-channel official uploads sometimes lack duration in flat search.
        # Neutral-low so the channel score (which is strong) still wins.
        return 0.3
    if duration < 30:
        return 0.0     # almost certainly a preview/snippet
    if duration < 90:
        return 0.2     # short — likely a sample
    if 120 <= duration <= 360:
        return 1.0     # canonical song length
    if 90 <= duration < 120 or 360 < duration <= 600:
        return 0.7     # plausible
    if 600 < duration <= 900:
        return 0.4     # long-ish — maybe a live/mix
    return 0.1         # >15min — very likely a compilation/mix


_NEG_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in NEGATIVE_KEYWORDS if " " not in k or "_" in k) + r")\b",
    re.IGNORECASE,
)
# Multi-word negatives can't use \b the same way; check them as substrings.
_NEG_MULTI = tuple(k for k in NEGATIVE_KEYWORDS if " " in k)


def _variant_adjustment(entry_title, query_lc):
    """Signed adjustment for variant keywords (cover / remix / live / …).

    When the title contains a variant word:
      - if the query ALSO asks for it → POSITIVE (operator wants this variant;
        the bonus is strong enough to beat the Topic-channel studio upload, which
        is NOT what they asked for)
      - if the query does NOT → NEGATIVE (penalty for an unwanted variant)

    Symmetric by design: ``remix`` is either the ask or the contamination, never
    neutral. Same family for live / acoustic / instrumental / reaction."""
    if not entry_title:
        return 0.0
    title_lc = entry_title.lower()
    matched = set()
    for m in _NEG_RE.finditer(title_lc):
        matched.add(m.group(1))
    for kw in _NEG_MULTI:
        if kw in title_lc:
            matched.add(kw)

    adj = 0.0
    for word in matched:
        # Treat multi-word negatives as flexible whitespace when scanning the query.
        pat = re.escape(word).replace(r"\ ", r"\s+")
        in_query = bool(re.search(r"\b" + pat + r"\b", query_lc))
        if in_query:
            if word in HEAVY_NEGATIVE:
                adj += 1.5
            elif word in MEDIUM_NEGATIVE:
                adj += 1.2
            else:
                adj += 0.8
        else:
            if word in HEAVY_NEGATIVE:
                adj -= 0.5
            elif word in MEDIUM_NEGATIVE:
                adj -= 0.4
            else:
                adj -= 0.3
    return adj


def _entry_score(entry, artist, title, query, orig_rank):
    """Composite score for one search result. Higher = better. The exact scale
    is arbitrary — only relative order matters."""
    et = entry.get("title") or ""
    query_lc = _norm(query)

    title_s = _title_score(et, artist, title)
    chan_s = _channel_score(entry, artist)
    dur_s = _duration_score(entry.get("duration"))
    var_s = _variant_adjustment(et, query_lc)

    # Log view count as a weak tiebreaker. A viral remix shouldn't outrank the
    # official upload just on views, but among otherwise-equal candidates it helps.
    vc = entry.get("view_count") or 0
    view_s = math.log10(vc + 1) / 10.0     # 1e6 views → 0.6, 1e4 → 0.4

    # Original YouTube rank as a weak tiebreaker (so equal-score results stay in
    # YouTube's order, not random).
    rank_s = 1.0 / (1.0 + orig_rank * 0.1)

    return (
        2.5 * title_s
        + 2.0 * chan_s
        + 0.5 * dur_s
        + var_s               # signed: + when query asked for the variant, − when unwanted
        + 0.3 * view_s
        + 0.2 * rank_s
    )


# ─── dedup + url normalization ────────────────────────────────────────────────

def _video_id_of(url):
    try:
        u = urlparse(url)
        if u.netloc.endswith("youtube.com"):
            return parse_qs(u.query).get("v", [None])[0]
        if u.netloc == "youtu.be":
            return u.path.lstrip("/")
    except Exception:
        pass
    return None


def _normalize_url(url):
    """ytsearch flat entries sometimes carry a bare video id or a youtu.be short
    link; normalize everything to the canonical watch URL the loader expects."""
    if not url:
        return None
    if url.startswith("http"):
        return url
    return "https://www.youtube.com/watch?v=" + url


def _format_duration(seconds):
    if seconds is None:
        return "?"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _format_views(n):
    if not n:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


# ─── public API ───────────────────────────────────────────────────────────────

def search(query, n=DEFAULT_N):
    """Run a YouTube search via yt_dlp's ``ytsearch`` and return results ranked
    for the "artist + track → official upload" intent.

    Returns a list of dicts sorted by score desc:
        ``{url, title, channel, duration, view_count, score}``
    Raises ``RuntimeError`` on any yt_dlp failure (network, parsing, bot-detection).
    """
    query = (query or "").strip()
    if not query:
        return []
    opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "default_search": "ytsearch",
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    except Exception as e:
        raise RuntimeError(f"YouTube search failed: {e}") from e
    entries = (info or {}).get("entries") or []
    return rank_entries(entries, query)


def rank_entries(entries, query):
    """Re-rank yt_dlp search entries for the "artist + track" intent.

    Pure function (no network) — exposed for testing and for callers that already
    hold the raw entries. Returns a list of dicts sorted by score desc; dedupes
    by video id. Stable on original YouTube order for ties."""
    artist, title = parse_query(query)
    out = []
    seen = set()
    for rank, e in enumerate(entries):
        if not e:
            continue
        url = _normalize_url(e.get("url") or e.get("id"))
        if not url:
            continue
        vid = _video_id_of(url) or url
        if vid in seen:
            continue
        seen.add(vid)
        out.append({
            "url": url,
            "title": e.get("title") or "(no title)",
            "channel": e.get("channel") or e.get("uploader") or "",
            "duration": e.get("duration"),
            "view_count": e.get("view_count"),
            "score": _entry_score(e, artist, title, query, rank),
            "_rank": rank,
        })
    # Stable sort: Python's sort preserves input order for ties, and ``out`` is
    # in YouTube-relevance order, so equal-score results stay in YouTube's order.
    out.sort(key=lambda r: -r["score"])
    return out


def format_result_line(r, idx=None):
    """One-line / two-line human rendering used by the TUI picker and CLI prints."""
    n = f"{idx:>2}. " if idx is not None else ""
    dur = _format_duration(r.get("duration"))
    views = _format_views(r.get("view_count"))
    return f"{n}{r['title']}\n      {r['channel']} · {dur} · {views} views"
