"""The amc grammar as a first-class TUI surface — parse it in, print it out.

Why this exists
---------------
The CLI's whole vocabulary is one string: ``amc l /2 w 4 m q c 0,250;900,7000 snap sw 66``. The TUI
re-expressed a SUBSET of that vocabulary as widgets, which meant three standing problems:

1. **Parity was a manual chase.** Every new amc token had to be re-implemented as a widget before a
   TUI operator could reach it, and the ones that hadn't been (``seed``, ``lk`` in some paths) were
   silently unreachable rather than visibly missing.
2. **Recipes were not portable.** An operator could not paste a recipe from the README, a chat
   message, or a crash-log line into the TUI, nor copy what the TUI was about to render back out.
3. **There was no single readable statement of "what will this render".** The panels held the
   answer, spread across five widgets.

So: one module that maps ``SessionState`` ⇄ amc string, both directions, and is the single parser
the command bar uses. Widgets stay the discoverable surface; the string stays the portable one.

``parse_amc`` is deliberately a strict left-to-right scan, NOT the CLI's ``args.index(token)``
lookup. ``index`` finds the FIRST occurrence, so a repeated token silently applies its first value,
and a value that happens to equal a key name (``m`` is also a legal... nothing, but ``lib`` is both
a mode value and a policy key) drives the CLI's own documented ``m lib`` special case. Scanning
pairwise has no such ambiguity: a key consumes its value and the scan resumes after it.
"""

from automixer.config import parse_stream_spec
from automixer.series import parse_series_token, SeriesError
from tui.state import MODES, LIB_POLICIES, TrackSpec

# Keys that take exactly one following value token.
VALUE_KEYS = {
    "l", "s", "ss", "w", "m", "c", "pr", "ek", "en", "lib", "lk",
    "sw", "fg", "env", "rv", "src2", "seed",
}
# Keys that are bare flags (no value follows).
FLAG_KEYS = {"snap", "nosnap", "fill", "nofill"}

ALL_KEYS = VALUE_KEYS | FLAG_KEYS


class AmcError(ValueError):
    """A malformed amc string — carries every problem found, not just the first."""


def parse_bands(spec):
    """Parse a ``c`` value into a list of TrackSpec.

    Grammar (identical to ``config_automix``): ``low,high`` pairs separated by ``;``, each
    optionally prefixed ``2:`` to pull that band from Source B. Extension: the literal word
    ``raw`` (alone) means the CLI's absent-``c`` default — one RAW pass-through band, no filter.
    That word exists because the TUI must be able to say "no bands" in a grammar whose way of
    saying it is to omit the token entirely, which a command bar cannot do once a band is set.
    """
    spec = (spec or "").strip()
    if not spec or spec == "raw":
        return [TrackSpec(0, 15000, bypass=True)]
    tracks = []
    for seg in spec.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        src2 = False
        if seg.startswith("2:"):
            src2 = True
            seg = seg[2:]
        if "," not in seg:
            raise AmcError(f"c: band {seg!r} needs low,high")
        low_s, _, high_s = seg.partition(",")
        try:
            low, high = int(low_s), int(high_s)
        except ValueError:
            raise AmcError(f"c: band {seg!r} needs whole-number Hz")
        if not (0 <= low < high):
            raise AmcError(f"c: band {low}-{high} needs 0 <= low < high")
        tracks.append(TrackSpec(low, high, source2=src2, bypass=False))
    if not tracks:
        raise AmcError("c: no bands parsed")
    return tracks


def format_bands(tracks):
    """Inverse of ``parse_bands`` — the ``c`` value for this band list."""
    if not tracks or all(t.bypass for t in tracks):
        return "raw"
    return ";".join(f"{'2:' if t.source2 else ''}{t.low},{t.high}"
                    for t in tracks if not t.bypass)


def _resolve_length(val, base):
    """``l`` accepts an absolute ms value or a ``/N``/``*N`` transform of the current one."""
    try:
        if val.startswith("/"):
            d = float(val[1:])
            if d == 0:
                raise AmcError("l: cannot divide by 0")
            return max(1, int(round(base / d)))
        if val.startswith("*"):
            return max(1, int(round(base * float(val[1:]))))
        return max(1, int(round(float(val))))
    except AmcError:
        raise
    except (ValueError, ZeroDivisionError):
        raise AmcError(f"l: not a number or /N, *N ({val!r})")


def is_series(text):
    """True when any token in the string is bracketed — the command bar routes those to the series
    field instead of applying them, so ``l [/2,/3]`` typed in the bar arms a 2-render sweep rather
    than failing to parse as a single value."""
    for tok in (text or "").split():
        try:
            if parse_series_token(tok) is not None:
                return True
        except SeriesError:
            return True
    return False


def parse_amc(text, base_length=0):
    """Parse an amc string into a plain dict of state updates.

    Returns ``(updates, errors)`` — updates is a dict of SessionState field → value for every token
    that parsed, errors is a list of human strings for every token that did not. BOTH are returned
    (rather than raising on the first problem) so the command bar can apply the good half of a
    mostly-right line and tell the operator exactly which token to fix.

    ``base_length`` is the current sample length, the base a ``/N`` or ``*N`` resolves against.
    """
    tokens = (text or "").split()
    if tokens and tokens[0] == "amc":
        tokens = tokens[1:]
    updates, errors = {}, []
    i = 0
    while i < len(tokens):
        key = tokens[i]
        if key in FLAG_KEYS:
            if key == "snap":
                updates["snap"] = True
            elif key == "nosnap":
                updates["snap"] = False
            elif key == "fill":
                updates["fill"] = True
            elif key == "nofill":
                updates["fill"] = False
            i += 1
            continue
        if key not in VALUE_KEYS:
            errors.append(f"unknown token {key!r} — known: {' '.join(sorted(ALL_KEYS))}")
            # Swallow the unknown key's VALUE too when the next token isn't itself a key, so one
            # typo yields one error. Without this, `zzz 1` reports twice ("zzz" then "1") and a
            # single mistyped key buries the real problem under a cascade of phantom ones.
            i += 2 if (i + 1 < len(tokens) and tokens[i + 1] not in ALL_KEYS) else 1
            continue
        if i + 1 >= len(tokens):
            errors.append(f"{key}: missing value")
            break
        val = tokens[i + 1]
        i += 2
        try:
            if key == "l":
                updates["sample_length_ms"] = _resolve_length(
                    val, updates.get("sample_length_ms", base_length) or base_length)
            elif key == "s":
                updates["speed"] = _num(float, val, "s", 0.1, 10.0)
            elif key == "ss":
                updates["sample_speed"] = _num(float, val, "ss", 0.1, 10.0)
            elif key == "w":
                updates["window_divider"] = _num(int, val, "w", 1, 10)
            elif key == "m":
                if val not in MODES:
                    raise AmcError(f"m: {val!r} not one of {', '.join(MODES)}")
                updates["mode"] = val
            elif key == "c":
                updates["tracks"] = parse_bands(val)
            elif key == "pr":
                parse_stream_spec(val)      # validate; the state keeps the raw spec string
                updates["streams_spec"] = val
            elif key == "ek":
                updates["euclid_k"] = _num(int, val, "ek", 1, 64)
            elif key == "en":
                updates["euclid_n"] = _num(int, val, "en", 1, 64)
            elif key == "lib":
                if not (val.startswith("sim") or val.startswith("con")):
                    raise AmcError(f"lib: {val!r} — expected sim(ilarity) or con(trast)")
                updates["lib_policy"] = "contrast" if val.startswith("con") else "similarity"
            elif key == "lk":
                updates["lib_clusters"] = _num(int, val, "lk", 1, 64)
            elif key == "sw":
                updates["swing"] = _num(float, val, "sw", 0.0, 100.0)
            elif key == "fg":
                updates["fill_gain_db"] = _num(float, val, "fg", -60.0, 0.0)
            elif key == "env":
                updates["env_pct"] = _num(float, val, "env", 0.0, 50.0)
            elif key == "rv":
                updates["reverse_prob"] = _num(float, val, "rv", 0.0, 1.0)
            elif key == "src2":
                updates["source2_path"] = val
            elif key == "seed":
                updates["seed"] = _num(int, val, "seed", -2**31, 2**31)
        except (AmcError, ValueError, IndexError) as e:
            errors.append(str(e) if isinstance(e, AmcError) else f"{key}: {e}")
    # euclid k <= n is a cross-token invariant — check it once, against the merged view of both
    # (a line that sets only k must still be validated against the k/n already on the state).
    if "euclid_k" in updates and "euclid_n" in updates:
        if updates["euclid_k"] > updates["euclid_n"]:
            errors.append(f"euclid: k ({updates['euclid_k']}) must be <= n ({updates['euclid_n']})")
            updates.pop("euclid_k")
            updates.pop("euclid_n")
    return updates, errors


def _num(cast, val, key, lo, hi):
    try:
        v = cast(float(val)) if cast is int else cast(val)
    except (TypeError, ValueError):
        raise AmcError(f"{key}: not a number ({val!r})")
    if not (lo <= v <= hi):
        raise AmcError(f"{key}: {v} out of range {lo}-{hi}")
    return v


def apply_amc(state, text):
    """Parse ``text`` and write every valid field onto ``state``. Returns the error list."""
    updates, errors = parse_amc(text, base_length=getattr(state, "sample_length_ms", 0))
    for field, value in updates.items():
        setattr(state, field, value)
    return errors


def format_amc(state, full=False):
    """Render the state as an amc string — the exact command the CLI would need to reproduce it.

    ``full=False`` (the default) prints only what applies to the ACTIVE mixer plus anything set away
    from its default, so the line stays readable and every token in it is load-bearing. ``full=True``
    prints every knob, for the copy-a-complete-recipe case.
    """
    p = [f"m {state.mode}", f"l {int(state.sample_length_ms)}", f"w {state.window_divider}"]
    if full or state.speed != 1.0:
        p.append(f"s {state.speed:g}")
    if full or state.sample_speed != 1.0:
        p.append(f"ss {state.sample_speed:g}")
    bands = format_bands(state.tracks)
    if full or bands != "raw":
        p.append(f"c {bands}")
    if full or state.mode == "q":
        p.append(f"ek {state.euclid_k}")
        p.append(f"en {state.euclid_n}")
        if not state.fill:
            p.append("nofill")
        if full or state.fill_gain_db != -6.0:
            p.append(f"fg {state.fill_gain_db:g}")
    if (full or state.mode == "poly") and state.streams_spec:
        p.append(f"pr {state.streams_spec}")
    if full or state.mode == "lib":
        p.append(f"lib {'con' if state.lib_policy == 'contrast' else 'sim'}")
        p.append(f"lk {state.lib_clusters}")
    if state.snap:
        p.append("snap")
    if full or state.swing:
        p.append(f"sw {state.swing:g}")
    if full or state.env_pct != 8.0:
        p.append(f"env {state.env_pct:g}")
    if full or state.reverse_prob:
        p.append(f"rv {state.reverse_prob:g}")
    if state.source2_path:
        p.append(f"src2 {state.source2_path}")
    seed = state.amc_seed() if hasattr(state, "amc_seed") else getattr(state, "seed", None)
    if seed is not None:
        p.append(f"seed {seed}")
    return "amc " + " ".join(p)
