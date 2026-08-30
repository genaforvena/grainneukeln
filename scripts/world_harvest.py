#!/usr/bin/env python3
"""world_harvest.py — build a WORLD-TRADITION clip corpus with a licence attached to every file.

The existing `downloads/ethnic/clips` set is 13 clips pulled off YouTube with **zero provenance**:
you cannot say, per file, who recorded it or under what terms. That corpus is fine to experiment
with and impossible to publish from. This harvester's whole point is the manifest, not the audio —
every clip it writes carries the archive.org identifier, the verbatim `licenseurl`, the uploader's
subject tags, the creator and the exact byte range it was cut from, so a wrong licence is traceable
to its item instead of being laundered into an anonymous folder.

Two things it deliberately does NOT claim:

  * A licence field is **self-declared by the uploader**. Recording it verbatim is provenance, not
    legal clearance, and this script never rewrites or normalises it.
  * The Great 78 Project (`collection:georgeblood`) carries **no per-item licence metadata at all** —
    checked 2026-08-29 on `78_le-flamenco-de-paris_...`: `licenseurl`, `rights` and
    `possible-copyright-status` are all null. Its public-domain status is a *collection-level* claim
    about pre-1972 recordings, which is a different kind of assertion from a per-item CC grant. So
    the `pd78` lane records `licence_kind=collection-claim` and never invents a URL.

Keyword search is noisy in both lanes — a Léo Ferré chanson called *Le Flamenco de Paris* matches
"flamenco" on title alone. Every candidate is therefore re-checked against the item's OWN subject
list before it is downloaded; a title-only match is rejected (`--loose` disables this, loudly).

AND A SUBJECT GATE IS STILL NOT A GENRE GATE, because a subject tag says what an item is ABOUT and
never what it IS. Measured over this repo's own 42-row corpus on 2026-08-30: **10 rows (24%) were
speech or talk radio**, every one of them past the subject gate legitimately — a 1916 Cambridge
lecture series filed as `balkan` (and handed the aksak7 grid), two podcasts, a talk show, a radio
interview about flamenco, and four music radio SHOWS. Every existing SKIP arm passed them: they are
real, licensed, audio, long enough and not near-silent. The failure direction is silent.

Two gates answer it and they are not alternatives — `--recheck` prints the census that says so:

  * **collection** (pre-download, free): archive.org files librivox, podcasts and radio shows into
    their own collections by FORMAT. Caught 9 of the 10, with zero false positives on music.
  * **measurement** (post-download): 2 axes on probe windows. Caught 6, of which **1 has no
    collection tell at all** (`gamelan-edc5dbd8`, "Art Monthly Talk Show", filed only under
    `opensource_audio`) and is therefore reachable by no metadata gate whatsoever.

The measured gate is NOT the rhythm-density floor that suggests itself. That was tried first and
MEASURED DEAD: beat density over all 42 clips spans 1.45..2.85 b/s, with the 2.5-hour lecture at
1.55 and a gnawa at 1.60 — all 42 clear the 0.8 b/s floor, so it separates nothing. The beat
detector's hallucinated grid is not merely unreliable, it is uniformly dense. See SPEECH_LER_MIN.

  usage:  scripts/world_harvest.py [--per 3] [--only slug,slug] [--lane cc|pd78|all] [--dry-run]
          scripts/world_harvest.py --recheck [--quarantine]   # census the corpus; move the speech out
  out:    downloads/world/clips/<slug>-<n>.wav        35 s, 44.1 kHz stereo
          downloads/world/MANIFEST.jsonl              one line per clip, provenance verbatim
          downloads/world/harvest.log
          downloads/world/quarantine/                          --quarantine moves, never deletes
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "downloads" / "world"
CLIPS = OUT / "clips"
MANIFEST = OUT / "MANIFEST.jsonl"
LOG = OUT / "harvest.log"

# NO CUT. The first version took a 35-second slice because the old ethnic clips are 35 s, and that
# repeated verbatim the mistake this repo already paid for and fixed on 2026-08-21: an input cap
# that looked like a budget was an AMPUTATION. The measurement that settled it — peak RSS is linear
# in feed length (~4.12 MB/s + ~230 MB base) and does NOT depend on the recipe (the most pathological
# and the calmest recipe differed by 108 KB out of five gigabytes) — means length costs memory, not
# correctness, and this node has 31 GB. Keep the whole track.
SILENCE_FLOOR_DBFS = -45.0 # a near-silent source yields a dead mix (0 beats), so drop it here
# Raised from 60 MB for the same reason the format preference below inverted: a full-length 24-bit
# FLAC of a 78 runs ~50 MB and a modern lossless track more, and capping bytes silently selects the
# most band-limited derivative available.
MAX_FETCH_BYTES = 400 * 1024 * 1024
BULK_TAG_LIMIT = 15        # more tags than this and the item describes a shelf, not a recording
NARROW_TAG_CHARS = 40      # a tag long enough to hold a sentence is not a genre label

# A SUBJECT TAG SAYS WHAT AN ITEM IS ABOUT, NEVER WHAT IT IS. `subject:("balkan")` is a genuine
# metadata gate and it is still the wrong one: a 1916 Cambridge lecture series on the Balkans
# carries subject `balkans`, and a podcast episode discussing the oud carries subject `oud`. Both
# are real, licensed, audio, long enough and not near-silent, so every SKIP arm above passes them —
# the failure direction is SILENT. Measured on this repo's own corpus 2026-08-30: 10 of 42 rows
# (24%) were speech or talk radio, not music.
#
# A COLLECTION is the opposite kind of claim: archive.org files librivox, podcasts and radio shows
# into their own collections by FORMAT, i.e. by what the item IS. Membership is therefore a gate and
# topicality is not. Measured catch on the 42-row corpus: 9 of the 10 contaminants, zero false
# positives on music.
#
# `audio_religion` is deliberately NOT here and the omission is measured, not an oversight: it is a
# SUBJECT collection like the tags above, and its one member in this corpus (`persian-080e0a3d`,
# "Sabke Man") reads pulse 0.597 — the third most rhythmic item of all 42. A subject collection
# smuggled into a format list is the same defect one ring in.
SPEECH_COLLECTIONS = frozenset({
    "librivoxaudio", "audio_bookspoetry", "librivox_audiobooks",
    "podcasts", "podcasts_miscellaneous", "podcast",
    "radioprograms", "radioshowarchive", "radioshowinbox", "radiostationarchives",
    "oralhistory", "audio_news", "audio_podcast", "spokenword", "lecture",
})

# THE POST-DOWNLOAD DISCRIMINATOR, AND WHY IT IS NOT THE ONE THAT WAS ASKED FOR.
# The brief proposed a rhythm-DENSITY floor, on the standing rule that the beat detector
# hallucinates a grid and cannot report "no rhythm". The rule is right and the remedy does not
# follow from it: MEASURED over all 42 clips, beat density spans 1.45..2.85 b/s with the 2.5-hour
# LECTURE at 1.55 and a gnawa at 1.60 — every single clip clears the 0.8 b/s floor, so the density
# gate separates NOTHING. The hallucinated grid is not merely unreliable, it is uniformly dense.
#
# Two axes that do separate, and they only work as a CONJUNCTION:
#   ler   low-energy rate — the share of frames under half the mean RMS. Speech pauses between
#         syllables and words; sustained music does not.
#   pulse the peak of the normalised autocorrelation of the onset envelope over musical lags
#         (30..300 BPM). Unlike a beat COUNT this can return ~0, i.e. it CAN say "no rhythm".
# Neither alone is usable: `pulse` alone also condemns `ethiopian-15e1bb37` (0.106), `soukous-04da23da`
# (0.115) and `kora-2a1f3ad4` (0.135), which are music with a loose pulse; `ler` alone also condemns
# the georgeblood 78s, whose shellac gaps and inter-track silence inflate it. The AND spares all of them.
#
# Thresholds are the MIDPOINTS of the measured gap on the cc lane, not round numbers:
#   ler    highest survivor 0.233 (carnatic-6677e027) .. lowest catch 0.288 (oud-c9e51a5a)  -> 0.26
#   pulse  lowest survivor  0.215 (carnatic-6400be30) .. highest catch 0.171 (gamelan-edc5dbd8) -> 0.19
# On the cc lane that is 6 caught, 6 speech, 0 false positives. Re-derive with --recheck; do not
# quote these numbers as still true of a corpus that has moved.
SPEECH_LER_MIN   = float(os.environ.get("WH_SPEECH_LER_MIN", "0.26"))
SPEECH_PULSE_MAX = float(os.environ.get("WH_SPEECH_PULSE_MAX", "0.19"))
SPEECH_PROBES    = 3       # windows spread across the track
SPEECH_WIN       = 20.0    # seconds per window

# The pd78 lane is EXEMPT from the measured gate and the exemption is a mechanism, not a
# convenience: both false positives the two axes produced on the whole corpus are georgeblood 78s
# (`fado-10371737` ler 0.443 / pulse 0.108, `koto-c5a41c40` 0.288 / 0.151), where shellac surface
# noise depresses pulse and the silence between medley sides inflates ler. Their columns are still
# MEASURED and written; only the skip is withheld, and the row says so.
SPEECH_GATE_LANES = ("cc",)

# slug | region | lane | archive.org subject term | the timeline its grains should land on.
# The pattern column is the point of the pairing: a source is ground on a grid from its OWN metric
# universe. A name not yet in NAMED_PATTERNS is listed here as the tradition's real shape and is
# what scripts/world_grind.sh needs the engine to learn.
TRADITIONS = [
    # -- Africa ------------------------------------------------------------------------------
    ("gnawa",        "Morocco",          "cc",   "gnawa",            "gnawa"),
    ("kora",         "Mande / W Africa", "cc",   "kora",             "bembe"),
    ("mbira",        "Zimbabwe",         "cc",   "mbira",            "bembe"),
    ("highlife",     "Ghana",            "cc",   "highlife",         "shiko"),
    ("soukous",      "Congo",            "cc",   "soukous",          "soukous"),
    ("ethiopian",    "Ethiopia",         "cc",   "ethiopian music",  "bell6"),
    ("taarab",       "Swahili coast",    "cc",   "taarab",           "maqsum"),
    # -- Middle East / Central Asia ------------------------------------------------------------
    ("qawwali",      "Punjab / Sindh",   "cc",   "qawwali",          "keherwa"),
    ("oud",          "Arab world",       "cc",   "oud",              "maqsum"),
    ("persian",      "Iran",             "cc",   "persian music",    "sheshohasht"),
    ("throatsinging","Tuva / Mongolia",  "cc",   "throat singing",   "aksak5"),
    ("shashmaqam",   "Uzbek / Tajik",    "cc",   "shashmaqam",       "aksak9"),
    # -- South / East / SE Asia -----------------------------------------------------------------
    ("gamelan",      "Java / Bali",      "cc",   "gamelan",          "colotomic"),
    ("hindustani",   "North India",      "cc",   "hindustani",       "teental"),
    ("carnatic",     "South India",      "cc",   "carnatic",         "adi"),
    ("koto",         "Japan",            "pd78", "koto",             "jajinmori"),
    ("gagaku",       "Japan",            "cc",   "gagaku",           "colotomic"),
    ("pansori",      "Korea",            "cc",   "pansori",          "jajinmori"),
    # -- Europe -----------------------------------------------------------------------------
    ("flamenco",     "Andalusia",        "cc",   "flamenco",         "buleria"),
    ("fado",         "Portugal",         "pd78", "fado",             "habanera"),
    ("rebetiko",     "Greece",           "cc",   "rebetiko",         "aksak9"),
    ("balkan",       "Balkans",          "cc",   "balkan",           "aksak7"),
    ("klezmer",      "Ashkenaz",         "cc",   "klezmer",          "freylekhs"),
    ("balalaika",    "Russia",           "pd78", "balalaika",        "polka2"),
    ("bagpipe",      "Scotland",         "pd78", "bagpipe",          "reel"),
    ("irish",        "Ireland",          "cc",   "irish traditional","jig"),
    ("polska",       "Sweden / Norway",  "cc",   "polska",           "polska"),
    ("joik",         "Sápmi",            "cc",   "joik",             "euclid"),
    ("georgian",     "Georgia",          "cc",   "georgian folk",    "aksak5"),
    ("tarantella",   "S Italy",          "pd78", "tarantella",       "tarantella"),
    ("csardas",      "Hungary",          "pd78", "csardas",          "polka2"),
    # -- The Americas + Pacific -----------------------------------------------------------------
    ("tango",        "Río de la Plata",  "pd78", "tango",            "habanera"),
    ("samba",        "Brazil",           "pd78", "samba",            "surdo"),
    ("maracatu",     "Pernambuco",       "cc",   "maracatu",         "surdo"),
    ("son",          "Cuba",             "pd78", "son cubano",       "clave23"),
    ("calypso",      "Trinidad",         "pd78", "calypso",          "cinquillo"),
    ("mariachi",     "Mexico",           "pd78", "mariachi",         "sesquialtera"),
    ("andean",       "Andes",            "cc",   "andean",           "huayno"),
    ("cajun",        "Louisiana",        "pd78", "cajun",            "reel"),
    ("hula",         "Hawaii",           "pd78", "hula",             "euclid"),
    ("yodel",        "Alps",             "pd78", "yodel",            "waltz3"),
]

# ORDER IS THE PREFERENCE, best first. The first version picked the SMALLEST usable file "because
# we only keep 35 s of it, so bytes are pure cost" — which is a rule that selects, every single
# time, the most heavily compressed and therefore most BAND-LIMITED derivative on the item. Measured
# on the corpus it built: 0 of 45 sources lossless (30 VBR MP3, 15 Ogg Vorbis) and content dying at
# 12.1-16.8 kHz. The pipeline itself is clean — a full-band white-noise source grinds out to 20.3 kHz
# at 320 kbps — so every kilohertz missing from those renders was thrown away HERE, at selection.
AUDIO_FORMATS = ("24bit Flac", "Flac", "WAVE", "VBR MP3", "MP3", "Ogg Vorbis", "128Kbps MP3")


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def curl_json(url: str, params: list[tuple[str, str]] | None = None, timeout: int = 45):
    """archive.org over curl — it honours the node's proxy env exactly like every other tool here."""
    cmd = ["curl", "-sS", "-m", str(timeout), "--get", url]
    for k, v in params or []:
        cmd += ["--data-urlencode", f"{k}={v}"]
    try:
        raw = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15)
    except subprocess.TimeoutExpired:
        return None
    if raw.returncode != 0 or not raw.stdout.strip():
        return None
    try:
        return json.loads(raw.stdout)
    except json.JSONDecodeError:
        return None


def search(lane: str, term: str, rows: int):
    if lane == "pd78":
        q = f'collection:(georgeblood) AND ("{term}")'
    else:
        # The NOT clause is a bandwidth saving, NOT the gate — a search index and an item's own
        # metadata can disagree, and a query-side exclusion produces no SKIP line anyone can read.
        # The gate that actually decides is collection_confirms() below, on the item's own metadata.
        deny = " OR ".join(sorted(SPEECH_COLLECTIONS))
        q = (f'mediatype:(audio) AND subject:("{term}") '
             f'AND licenseurl:(*creativecommons* OR *publicdomain*) '
             f'AND NOT collection:({deny})')
    params = [("q", q), ("rows", str(rows)), ("output", "json"), ("sort[]", "downloads desc")]
    for f in ("identifier", "title", "creator", "licenseurl", "subject", "year", "collection"):
        params.append(("fl[]", f))
    data = curl_json("https://archive.org/advancedsearch.php", params)
    if not data:
        return []
    return data.get("response", {}).get("docs", [])


def md_title(meta: dict) -> str:
    return meta.get("metadata", {}).get("title", "") or ""


def subject_tags(meta: dict) -> list[str]:
    subj = meta.get("metadata", {}).get("subject", [])
    if isinstance(subj, str):
        # archive.org returns a single subject as a bare string, and semicolon/comma-joined
        # tag soup as one field — split it or a 30-tag bulk upload looks like one tag.
        subj = re.split(r"[;,]", subj)
    return [str(s).strip().lower() for s in subj if str(s).strip()]


def subject_confirms(meta: dict, term: str) -> tuple[bool, str]:
    """Re-check the term against the item's OWN metadata. Two separate failures, named apart.

    A title-only match is a false hit (`Le Flamenco de Paris` is a Leo Ferre chanson). But so is a
    match inside a BULK upload tagged with thirty traditions at once — "Vintage Indian Music 37"
    carries `qawwali` among its tags and is a Lata Mangeshkar film song. A substring test over the
    joined tag list passes both. So the term must land in a tag SHORT enough to be about this item,
    or in the title with a tag corroborating it.
    """
    term = term.lower()
    tags = subject_tags(meta)
    if len(tags) > BULK_TAG_LIMIT:
        return False, f"bulk upload ({len(tags)} subject tags) — its tags describe a shelf, not a track"
    title = str(meta.get("metadata", {}).get("title", "")).lower()
    for tag in tags:
        if term in tag and len(tag) <= NARROW_TAG_CHARS:
            return True, "subject tag"
    if term in title and any(term in t for t in tags):
        return True, "title + subject"
    if any(term in t for t in tags):
        return False, "term only inside a wide tag — not specific to this item"
    return False, "term not in the item's own subject tags (title-only match)"


def collections_of(meta: dict) -> list[str]:
    c = meta.get("metadata", {}).get("collection", [])
    if isinstance(c, str):
        c = [c]
    return [str(x).strip().lower() for x in c if str(x).strip()]


def collection_confirms(meta: dict) -> tuple[bool, str]:
    """Reject an item whose OWN collections say it is a book, a podcast or a radio show.

    This is the pre-download half of the subject-tag defect. It costs one metadata read that was
    already being made, and it is the only one of the two halves that saves the download.
    """
    hit = sorted(set(collections_of(meta)) & SPEECH_COLLECTIONS)
    if hit:
        return False, "speech-format collection %s — a show/book/podcast, not a recording" % ",".join(hit)
    return True, ""


def speech_axes(path: Path, dur: float | None) -> dict:
    """MEASURED speech-vs-music axes over probe windows spread across the track.

    Returns `{"ler":…, "pulse":…, "cov":…, "n":…}` or `{"why": …}` when it could not measure.
    It NEVER returns a number it did not measure: an absent librosa, an unreadable file or a
    too-short track render `why`, and the caller writes `unmeasured` rather than a passing verdict.

    COVERAGE TRAVELS WITH THE READING. The probes total SPEECH_PROBES * SPEECH_WIN seconds against a
    corpus whose median track is 434 s, so a typical reading covers ~14% and the 2.5-hour lecture
    0.7%. A window narrower than its subject reports a SAMPLE, not a state, and `cov` is what lets a
    consumer see which one it is holding.
    """
    try:
        import numpy as np
        import librosa
    except ImportError:
        venv = ROOT / ".venv" / "bin" / "python"
        if not venv.exists():
            return {"why": "librosa absent and no repo venv to re-exec into"}
        r = subprocess.run([str(venv), __file__, "--speech", str(path), str(dur or 0)],
                           capture_output=True, text=True)
        try:
            return json.loads(r.stdout.strip())
        except (ValueError, json.JSONDecodeError):
            return {"why": "venv re-exec produced no reading"}

    if dur is None:
        return {"why": "no duration known — cannot place a probe window"}
    if dur < 5:
        return {"why": "too short to probe (dur=%.1fs)" % dur}
    # The probes must not OVERLAP, or `cov` double-counts and can exceed 1.0 — measured live on
    # `carnatic-6677e027` (a 31 s track), where three 20 s windows summed to cov=1.917. A coverage
    # term that can report more than the whole track is not a coverage term. Drop probes until they
    # fit, and clamp as a second line of defence.
    win = min(SPEECH_WIN, dur)
    nprobe = max(1, min(SPEECH_PROBES, int(dur // win)))
    if nprobe <= 1 or dur <= win:
        offs, win = [0.0], win
    else:
        offs = [max(0.0, min(dur - win, dur * (i + 1) / (nprobe + 1) - win / 2))
                for i in range(nprobe)]

    lers, pulses, probed = [], [], 0.0
    probe = path.with_suffix(".speech.wav")
    try:
        for off in offs:
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(off), "-t", str(win),
                                "-i", str(path), "-ac", "1", "-ar", "22050", str(probe)],
                               capture_output=True)
            if r.returncode != 0 or not probe.exists():
                continue
            try:
                y, sr = librosa.load(str(probe), sr=22050, mono=True)
            except Exception:
                continue
            if len(y) < sr:
                continue
            S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
            rms = librosa.feature.rms(S=S)[0]
            if rms.mean() <= 0:
                continue
            lers.append(float((rms < 0.5 * rms.mean()).mean()))
            o = librosa.onset.onset_strength(S=librosa.power_to_db(S ** 2), sr=sr)
            o = o - o.mean()
            if o.std() < 1e-9:
                pulses.append(0.0)
            else:
                ac = librosa.autocorrelate(o, max_size=len(o))
                ac = ac / (ac[0] + 1e-12)
                fps = sr / 512.0
                lo, hi = int(fps * 60 / 300), min(int(fps * 60 / 30), len(ac) - 1)
                pulses.append(float(ac[lo:hi].max()) if hi > lo else 0.0)
            probed += len(y) / sr
    finally:
        probe.unlink(missing_ok=True)

    if not lers or not pulses:
        return {"why": "no probe window was readable"}
    import statistics
    return {"ler": round(statistics.median(lers), 3),
            "pulse": round(statistics.median(pulses), 3),
            "cov": round(min(1.0, probed / dur), 4), "n": len(lers)}


def speech_verdict(ax: dict, lane: str) -> tuple[str, str]:
    """`(verdict, why)` — one of speech / music / unmeasured / exempt-<lane>.

    An unmeasurable reading is its OWN word. Folding it into `music` would make a missing
    interpreter indistinguishable from a passing measurement, which is the silent-fallback shape
    this gate exists to remove.
    """
    if "why" in ax:
        return "unmeasured", ax["why"]
    hot = ax["ler"] >= SPEECH_LER_MIN and ax["pulse"] <= SPEECH_PULSE_MAX
    detail = "ler=%.3f pulse=%.3f cov=%.3f n=%d" % (ax["ler"], ax["pulse"], ax["cov"], ax["n"])
    if not hot:
        return "music", detail
    if lane not in SPEECH_GATE_LANES:
        return "exempt-%s" % lane, detail + " — over the speech thresholds but the lane is exempt"
    return "speech", detail


def pick_file(meta: dict):
    """Highest-fidelity usable derivative: best FORMAT first, then LARGEST within that format.

    Both keys point the same way and both are the opposite of the first version. Lossless beats
    lossy outright, and inside one lossy format a bigger file is a higher bitrate, i.e. a higher
    lowpass. Bytes are not the cost being minimised here — bandwidth is the thing being preserved.
    """
    best = None
    for f in meta.get("files", []):
        fmt = f.get("format")
        if fmt not in AUDIO_FORMATS:
            continue
        try:
            size = int(f.get("size", 0))
        except (TypeError, ValueError):
            continue
        if size <= 0 or size > MAX_FETCH_BYTES:
            continue
        rank = (AUDIO_FORMATS.index(fmt), -size)
        if best is None or rank < best[0]:
            best = (rank, f)
    return best[1] if best else None


def top_freq_khz(path: Path) -> float | None:
    """The highest frequency carrying energy within 60 dB of the peak, measured mid-file.

    Published per clip so "frequencies preserved" is a MEASURED column and not an assertion —
    a source that was already lowpassed at 12 kHz by whoever encoded it cannot be un-lowpassed by
    any care taken downstream, and the manifest should say which clips those are.
    """
    try:
        import numpy as np
    except ImportError:
        # numpy lives in the repo venv, not in the system interpreter, and a harvest launched with
        # plain `python3` therefore wrote `top_freq_khz: null` on EVERY row — a measurement column
        # silently absent is worse than no column, because a reader takes null for "unmeasurable"
        # rather than "we ran the wrong interpreter". Re-exec this one measurement in the venv.
        venv = ROOT / ".venv" / "bin" / "python"
        if not venv.exists():
            return None
        r = subprocess.run([str(venv), __file__, "--measure", str(path)],
                           capture_output=True, text=True)
        try:
            return float(r.stdout.strip())
        except ValueError:
            return None
    probe = path.with_suffix(".probe.wav")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-ac", "1",
                        "-ar", "44100", "-f", "wav", str(probe)], capture_output=True)
    try:
        if r.returncode != 0 or not probe.exists():
            return None
        import array
        import wave
        with wave.open(str(probe)) as w:
            n = 1 << 15
            if w.getnframes() < n:
                return None
            w.setpos(w.getnframes() // 2)
            d = array.array("h")
            d.frombytes(w.readframes(n))
            sr = w.getframerate()
        x = np.array(d, dtype=float)[:n]
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        freqs = np.fft.rfftfreq(len(x), 1 / sr)
        loud = np.where(spec > spec.max() * 10 ** (-60 / 20))[0]
        return round(float(freqs[loud[-1]]) / 1000, 1) if len(loud) else None
    finally:
        probe.unlink(missing_ok=True)


def mean_dbfs(path: Path) -> float | None:
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", p.stderr)
    return float(m.group(1)) if m else None


def duration_of(path: Path) -> float | None:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return None


def clip_slug(tradition, ident):
    """`<tradition>-<8 hex of the identifier>`, NOT `<tradition>-<counter>`.

    The counter version restarted at 0 on every run while `seen` only de-duplicated identifiers,
    so a second run wrote a DIFFERENT recording into `gnawa-0.wav` and appended a second `gnawa-0`
    row — leaving the first row's licence and archive.org id pointing at audio that had been
    replaced underneath it. Not a cosmetic collision: it silently attributes one item's licence to
    another item's sound, the exact failure this whole manifest exists to make impossible. Keying
    on the identifier makes a re-harvest idempotent instead.
    """
    import hashlib

    return "%s-%s" % (tradition, hashlib.sha1(ident.encode()).hexdigest()[:8])


def harvest_one(slug, region, lane, term, pattern, want, dry, loose, seen):
    got, tried = 0, 0
    for doc in search(lane, term, rows=want * 8):
        if got >= want:
            break
        ident = doc.get("identifier")
        if not ident or ident in seen:
            continue
        seen.add(ident)
        tried += 1
        if tried > want * 8:
            break

        meta = curl_json(f"https://archive.org/metadata/{ident}")
        if not meta:
            log(f"  SKIP {ident}: metadata unreadable")
            continue
        ok, why = subject_confirms(meta, term)
        if not ok and lane == "pd78":
            # A title-only FALLBACK for the Great 78 lane, and note what it is NOT for. The first
            # run returned 0 clips from 15 pd78 traditions, and the guess was "georgeblood never
            # tags genre". That guess is WRONG and the manifest says so: the live rows carry
            # `["LP","78rpm","Tango"]`, `["78rpm","Samba"]`, `["Calypso","78rpm"]` — the genre IS
            # in `subject` for the western repertoire, and 7 of 8 pd78 clips came in through the
            # normal subject gate. What actually fails is the NON-anglophone shelf: a Japanese koto
            # 78 is titled `78_title-in-japanese_...` with no English genre tag anywhere, so the
            # subject gate can only ever reject it. This fallback exists for THAT case, and its
            # cost is visible: the one clip it admitted here (`samba-0`) is a Veloz-and-Yolanda
            # dance-instruction record, not a samba. Hence `match_basis` in every row.
            title = str(md_title(meta)).lower()
            if term.lower() in title:
                ok, why = True, "title-only (georgeblood: genre is never in subject)"
        if not ok and not loose:
            log(f"  SKIP {ident}: {why}")
            continue

        # The subject gate above asked what the item is ABOUT; this one asks what it IS. `--loose`
        # does NOT disable it — loose exists to widen the TOPIC match, and a librivox lecture is not
        # a loose match for a tradition, it is a different medium.
        okc, whyc = collection_confirms(meta)
        if not okc:
            log(f"  SKIP {ident}: {whyc}")
            continue

        md = meta.get("metadata", {})
        licenceurl = md.get("licenseurl")
        if lane == "cc":
            if not licenceurl:
                log(f"  SKIP {ident}: no licenseurl on the item")   # the whole point — never guess
                continue
            licence_kind = "item-declared"
        else:
            licence_kind = "collection-claim"   # georgeblood carries no per-item licence at all

        f = pick_file(meta)
        if not f:
            log(f"  SKIP {ident}: no usable audio derivative under {MAX_FETCH_BYTES} bytes")
            continue

        url = ("https://archive.org/download/" + urllib.parse.quote(ident) + "/"
               + urllib.parse.quote(f["name"]))
        if dry:
            log(f"  WOULD {clip_slug(slug, ident)}: {ident} [{licence_kind}] {licenceurl or '-'} :: {f['name']}")
            got += 1
            continue

        CLIPS.mkdir(parents=True, exist_ok=True)
        cslug = clip_slug(slug, ident)
        tmp = CLIPS / f".{cslug}.src"
        dl = subprocess.run(["curl", "-sSL", "-m", "300", "-o", str(tmp), url])
        if dl.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 10000:
            log(f"  SKIP {ident}: download failed")
            tmp.unlink(missing_ok=True)
            continue

        dur = duration_of(tmp)
        if not dur or dur < 20:
            log(f"  SKIP {ident}: too short to be a track (dur={dur})")
            tmp.unlink(missing_ok=True)
            continue

        clip = CLIPS / f"{cslug}.wav"
        cut = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(tmp),
             "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(clip)],
            capture_output=True, text=True)
        tmp.unlink(missing_ok=True)
        if cut.returncode != 0 or not clip.exists() or clip.stat().st_size < 100000:
            log(f"  SKIP {ident}: ffmpeg convert failed")
            clip.unlink(missing_ok=True)
            continue

        loud = mean_dbfs(clip)
        if loud is not None and loud < SILENCE_FLOOR_DBFS:
            log(f"  SKIP {ident}: near-silent ({loud} dBFS) — a dead source grinds to a dead mix")
            clip.unlink(missing_ok=True)
            continue

        # The post-download half. It costs the download it cannot prevent, which is exactly why the
        # collection gate above exists — but a talk show filed under `opensource_audio` carries no
        # collection tell at all (`gamelan-edc5dbd8`, "Art Monthly Talk Show"), and only a
        # measurement catches it. The two remedies are not alternatives.
        ax = speech_axes(clip, dur)
        verdict, vwhy = speech_verdict(ax, lane)
        if verdict == "speech":
            log(f"  SKIP {ident}: measured SPEECH not music ({vwhy})")
            clip.unlink(missing_ok=True)
            continue
        if verdict in ("unmeasured",) or verdict.startswith("exempt-"):
            # Loud on purpose: a gate that could not run must not read like a gate that passed.
            log(f"  KEEP {ident}: speech gate {verdict} — {vwhy}")

        row = {
            "slug": cslug, "tradition": slug, "region": region, "lane": lane,
            "pattern": pattern, "search_term": term,
            "identifier": ident, "item_url": f"https://archive.org/details/{ident}",
            "title": md.get("title"), "creator": md.get("creator"), "year": md.get("year"),
            "licenceurl": licenceurl, "licence_kind": licence_kind,
            "subject": md.get("subject"), "collection": md.get("collection"),
            "source_file": f["name"], "source_format": f.get("format"),
            "source_url": url, "match_basis": why,
            "duration_s": round(dur, 1), "cut": None,   # the WHOLE track — see the NO CUT note
            "mean_dbfs": loud, "top_freq_khz": top_freq_khz(clip),
            # MEASURED columns, so "is this corpus music?" is answerable from the manifest instead
            # of being re-estimated from titles. `speech_cov` is the share of the track actually
            # probed — read it before reading the two axes.
            "speech_ler": ax.get("ler"), "speech_pulse": ax.get("pulse"),
            "speech_cov": ax.get("cov"), "speech_verdict": verdict,
            "speech_why": vwhy,
            "clip": str(clip.relative_to(ROOT)),
            "harvested": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with MANIFEST.open("a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        log(f"  OK   {cslug}  {licence_kind}  {licenceurl or 'georgeblood'}  :: {md.get('title')}")
        got += 1

    return got


def recheck(quarantine: bool = False) -> int:
    """Re-measure the existing manifest. Prints one line per clip and a census by verdict.

    Every number this file's comments quote came from here. A threshold calibrated against a corpus
    ROTS as the corpus moves, so re-run this rather than trusting the constants.
    """
    if not MANIFEST.exists():
        log("recheck: no manifest at %s" % MANIFEST)
        return 2
    rows = []
    for line in MANIFEST.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    counts, coll_hits, missing = {}, 0, 0
    by_coll, by_measure = set(), set()
    for r in rows:
        clip = ROOT / r.get("clip", "")
        colls = r.get("collection") or []
        if isinstance(colls, str):
            colls = [colls]
        cl = sorted(set(c.strip().lower() for c in colls) & SPEECH_COLLECTIONS)
        if cl:
            coll_hits += 1
            by_coll.add(r.get("slug"))
        if not clip.exists():
            missing += 1
            print("%-24s CLIP-MISSING%s" % (r.get("slug"), "  collection:" + ",".join(cl) if cl else ""))
            counts["clip-missing"] = counts.get("clip-missing", 0) + 1
            continue
        ax = speech_axes(clip, r.get("duration_s"))
        v, why = speech_verdict(ax, r.get("lane", "cc"))
        r["speech_ler"], r["speech_pulse"] = ax.get("ler"), ax.get("pulse")
        r["speech_cov"], r["speech_verdict"], r["speech_why"] = ax.get("cov"), v, why
        counts[v] = counts.get(v, 0) + 1
        if v == "speech":
            by_measure.add(r.get("slug"))
        print("%-24s %-14s %s%s  :: %s" % (
            r.get("slug"), v, why,
            ("  collection:" + ",".join(cl)) if cl else "",
            (r.get("title") or "")[:44]), flush=True)
    n = len(rows)
    print("\n=== %d row(s) ===" % n)
    for k in sorted(counts):
        print("  %-14s %d" % (k, counts[k]))
    print("  %-14s %d  (pre-download gate would have refused these without downloading)"
          % ("speech-collection", coll_hits))
    # The UNION, computed, not bounded. `speech + speech-collection` is not the contamination
    # count: the two gates overlap heavily by design, and printing their sum would inflate the very
    # number this mode exists to measure.
    union, both = by_coll | by_measure, by_coll & by_measure
    print("  contamination: %d of %d (%.0f%%) — %d by collection only, %d by measurement only, "
          "%d by both" % (len(union), n, 100.0 * len(union) / n if n else 0,
                          len(by_coll - by_measure), len(by_measure - by_coll), len(both)))
    if quarantine:
        QUAR = OUT / "quarantine"
        moved, annotated = 0, []
        for r in rows:
            slug = r.get("slug")
            if slug not in union:
                annotated.append(r)
                continue
            clip = ROOT / r.get("clip", "")
            reasons = []
            if slug in by_coll:
                reasons.append("speech-format collection")
            if slug in by_measure:
                reasons.append("measured speech")
            r["quarantined"] = " + ".join(reasons)
            r["quarantined_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if clip.exists():
                QUAR.mkdir(parents=True, exist_ok=True)
                dest = QUAR / clip.name
                clip.rename(dest)
                r["clip"] = str(dest.relative_to(ROOT))
                moved += 1
            annotated.append(r)
        with MANIFEST.open("w") as fh:
            for r in annotated:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("  quarantined: %d clip(s) moved to %s; %d manifest row(s) annotated"
              % (moved, QUAR.relative_to(ROOT), len(union)))
    only_m = sorted(by_measure - by_coll)
    if only_m:
        print("  measurement-only (no collection tell — the pre-download gate CANNOT catch these): %s"
              % ", ".join(only_m))
    print("  thresholds in force: ler>=%.3f AND pulse<=%.3f, gate lanes %s"
          % (SPEECH_LER_MIN, SPEECH_PULSE_MAX, ",".join(SPEECH_GATE_LANES)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=3, help="clips per tradition")
    ap.add_argument("--only", default="", help="comma-separated tradition slugs")
    ap.add_argument("--lane", default="all", choices=["all", "cc", "pd78"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--patterns", action="store_true",
                    help="print tradition<TAB>grid from the CURRENT table and exit — the manifest "
                         "stores whatever the pairing was at harvest time, and the pairing is CODE, "
                         "so a consumer must re-read it here instead of trusting a stale copy")
    ap.add_argument("--quarantine", action="store_true",
                    help="with --recheck: MOVE every contaminated clip out of clips/ into "
                         "quarantine/ and annotate its manifest row. It moves rather than deletes — "
                         "these clips ARE the evidence for the contamination rate, and a gate that "
                         "destroys its own counterexamples cannot be re-audited when it drifts")
    ap.add_argument("--recheck", action="store_true",
                    help="re-measure the EXISTING manifest against both gates and print a census — "
                         "the contamination rate is a measurement, not an estimate from titles, and "
                         "the thresholds in this file must be re-derived here rather than quoted")
    ap.add_argument("--loose", action="store_true",
                    help="accept title-only keyword matches (noisy — says so per hit)")
    args = ap.parse_args()

    if args.patterns:
        for slug, _region, _lane, _term, pattern in TRADITIONS:
            print(f"{slug}\t{pattern}")
        return 0

    if args.recheck:
        return recheck(quarantine=args.quarantine)

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    OUT.mkdir(parents=True, exist_ok=True)
    seen = set()
    if MANIFEST.exists():
        for line in MANIFEST.read_text().splitlines():
            try:
                seen.add(json.loads(line)["identifier"])
            except Exception:
                pass

    if args.loose:
        log("LOOSE: title-only matches accepted — expect wrong-tradition sources in the corpus")

    total = 0
    for slug, region, lane, term, pattern in TRADITIONS:
        if only and slug not in only:
            continue
        if args.lane != "all" and lane != args.lane:
            continue
        log(f"{slug} ({region}, lane={lane}, term='{term}', grid={pattern})")
        total += harvest_one(slug, region, lane, term, pattern, args.per,
                             args.dry_run, args.loose, seen)

    log(f"=== harvested {total} clip(s); manifest {MANIFEST} ===")
    return 0 if total else 1


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--speech":
        # The re-exec entry point for speech_axes above, same shape as --measure: the repo venv
        # holds librosa and a harvest launched with plain `python3` cannot see it.
        print(json.dumps(speech_axes(Path(sys.argv[2]), float(sys.argv[3]) or None)))
        sys.exit(0)
    if len(sys.argv) == 3 and sys.argv[1] == "--measure":
        # The re-exec entry point for top_freq_khz above. Prints one number or nothing.
        v = top_freq_khz(Path(sys.argv[2]))
        if v is not None:
            print(v)
        sys.exit(0)
    sys.exit(main())
