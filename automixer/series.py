"""Series runs — expand one or more amc parameters across a list or numeric range, then render the
cartesian product of every expanded parameter. A single command produces N grinds instead of one.

Grammar
-------
A series token is any amc value wrapped in square brackets: ``[...]``. Two forms inside:

* **List** — comma-separated values: ``[100,200,300]`` · ``[/2,/3,/4]`` · ``[rw,q,poly]``.
* **Range** — ``start:stop:step`` (numeric only): ``[100:300:50]`` → 100, 150, 200, 250, 300.

The square brackets never appear elsewhere in the amc grammar (``c 0,250;...`` and ``pr 4;3`` use
commas and semicolons *inside* a single value, never brackets), so the series form is unambiguous.

Behaviour
---------
When ANY amc parameter is bracketed, the command expands to one render per cartesian combination:

* ``amc l [/2,/3,/4]``                         → 3 renders
* ``amc l [100:300:50]``                       → 5 renders (100, 150, 200, 250, 300)
* ``amc s [0.8,1.0,1.2] ss [1.0,1.5]``         → 6 renders (3 × 2)
* ``amc l [/2,/3] m [rw,q]``                   → 4 renders
* ``amc seed [1,2,3,4,5]``                     → 5 renders of the same recipe, only RNG differs

Parameters NOT bracketed stay constant across every combination (their value is held while the
bracketed ones sweep). Ratios inside a list (``/2``, ``*3``) resolve against the current base at
expand time, exactly as a single ``l /2`` would.

The expander is PURE: it consumes amc tokens and yields amc-token-lists. It knows nothing about
AutoMixerConfig — the caller runs each expanded token-list through the existing config_automix path,
so every series render is identical to a single-shot render with those resolved values. No new code
reaches the DSP.
"""

import re

# A series token: ``[...]`` — at least the brackets; the body may be empty (we raise on that case
# explicitly so the operator gets a clear "empty series" message instead of a silent no-op).
_SERIES_RE = re.compile(r"^\[(.*)\]$")
# Numeric range body: ``start:stop:step`` — all three are floats (negative speeds, fractional steps).
# Exactly two colons; a single colon (``[1:5]``) is treated as a malformed range, not a list of two.
_RANGE_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*:\s*(-?\d+(?:\.\d+)?)\s*:\s*(-?\d+(?:\.\d+)?)$")

# Parameters a series can sweep. Constrained so a typo (``amc z [1,2,3]``) is reported instead of
# silently producing one render per value of an unknown key. ``seed`` is included because grinding
# the same recipe N times with different RNGs is the canonical "variance pack" — same params,
# different grain picks, useful for cherry-picking the best of N.
SERIES_PARAMS = frozenset({
    "l", "s", "ss", "w", "m",
    "ek", "en", "sw", "fg", "lk",
    "lib",            # the policy word (sim/con) — sweepable like an enum
    "seed",
})


class SeriesError(ValueError):
    """Raised on a malformed series token (unknown param, bad range, zero step, empty list).

    A dedicated subclass (not bare ValueError) so callers can distinguish a series-parse failure
    from any other ValueError in the amc path and surface it as a single actionable message."""


def _split_top_level(body, sep=","):
    """Split ``body`` on ``sep`` at the top level only — brackets/parens nested inside a value are
    not split. Currently the series body has no nesting (the amc grammar is flat), but this keeps a
    future ``c`` series (each entry itself a ``low,high;...`` string) parseable without surprises."""
    out = []
    depth = 0
    cur = []
    for ch in body:
        if ch in "[(":
            depth += 1
            cur.append(ch)
        elif ch in "])":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    last = "".join(cur).strip()
    if last:
        out.append(last)
    return out


def _expand_range_body(body):
    """Expand a ``start:stop:step`` body into a list of numeric strings.

    Step sign is forced to match (stop - start): ``[300:100:50]`` is a descending range and yields
    300, 250, 200, 150, 100. Zero step is rejected (would loop forever). The endpoints are
    inclusive — ``[100:300:100]`` yields 100, 200, 300 (three values, not two).
    """
    m = _RANGE_RE.match(body.strip())
    if not m:
        raise SeriesError(f"Not a numeric range (need start:stop:step): {body!r}")
    start, stop, step = float(m.group(1)), float(m.group(2)), float(m.group(3))
    if step == 0:
        raise SeriesError(f"Range step cannot be 0: {body!r}")
    # Force the step sign to match the direction so [300:100:50] descends and [100:300:50] ascends.
    if stop < start and step > 0:
        step = -step
    elif stop > start and step < 0:
        step = -step

    vals = []
    # Use a small epsilon on the inclusive bound so float wobble (0.1+0.1+0.1 = 0.30000000000000004)
    # never drops or repeats the endpoint.
    eps = abs(step) * 1e-6
    v = start
    if step > 0:
        while v <= stop + eps:
            vals.append(_fmt_num(v))
            v += step
    else:
        while v >= stop - eps:
            vals.append(_fmt_num(v))
            v += step
    if not vals:
        raise SeriesError(f"Range is empty: {body!r}")
    return vals


def _fmt_num(v):
    """Render a numeric value back as the cleanest valid amc token: ``2.0`` → ``"2"``, ``2.5`` →
    ``"2.5"``, ``-3`` → ``"-3"``. This keeps expanded filenames and recipe strings readable —
    ``s2`` not ``s2.0`` — and matches what an operator would type by hand."""
    if v == int(v):
        return str(int(v))
    return repr(float(v))


def parse_series_token(tok):
    """If ``tok`` is a bracketed series token, return a list of the expanded raw value strings
    (one per combination entry); otherwise return ``None`` (not a series).

    Returned values are STRINGS — they re-enter the normal amc parser unchanged. So ``[/2,/3]``
    yields ``["/2", "/3"]`` and the existing ``l``-resolution code applies each one. A range body
    is expanded to its numeric string forms (``["100","150","200"]``) for the same reason.
    """
    m = _SERIES_RE.match(tok)
    if not m:
        return None
    body = m.group(1).strip()
    if not body:
        raise SeriesError("Empty series token: []")
    # Range form: exactly two top-level colons and a numeric triple. Detect BEFORE the comma split
    # so a single value with a colon (none currently exist in amc, but be safe) doesn't confuse us.
    if body.count(":") == 2 and _RANGE_RE.match(body):
        return _expand_range_body(body)
    # List form: split on commas, each entry is a raw value (number, /N, *N, mode word, sim/con…).
    items = _split_top_level(body, ",")
    if len(items) < 2:
        raise SeriesError(f"Series list needs at least 2 values: {tok!r}")
    return items


def _find_series_params(tokens):
    """Walk an amc token list and return ``{param_name: [values]}`` for every bracketed param.

    A series param is a key token (one of SERIES_PARAMS) immediately followed by a bracketed value
    token. Unknown keys with brackets are rejected — better to fail loudly than silently render one
    extra grind for a misspelled param. Non-bracketed params are passed through untouched (they will
    be applied to every combination as constants).

    Returns (series_dict, stripped_tokens) where ``stripped_tokens`` is the token list with every
    series value replaced by a placeholder — the caller expands the cartesian product and rewrites
    one placeholder per combination.
    """
    series = {}
    i = 0
    # We do not mutate while iterating; build a new list so the caller can iterate combinations.
    out = list(tokens)
    while i < len(out):
        key = out[i]
        if key in SERIES_PARAMS and i + 1 < len(out):
            expanded = parse_series_token(out[i + 1])
            if expanded is not None:
                series[key] = expanded
                # Leave the key in place; the value placeholder is replaced per-combination below.
                # We mark the slot with a sentinel so the cartesian expander knows where to write.
                out[i + 1] = ("__series__", key)
                i += 2
                continue
        i += 1
    return series, out


def expand_amc_series(tokens):
    """Expand an amc token list with bracketed series params into a list of plain amc token lists,
    one per cartesian combination.

    Each output list is a fully-resolved amc token sequence — pass it to the existing
    config_automix and it builds a single config, exactly as if the operator had typed those values
    by hand. The cartesian product iterates in the order the params appear in the input (last param
    varies fastest) so related combos stay adjacent in the output list.

    If no token is bracketed, returns ``[tokens]`` — a single-element list — so callers can treat
    the single-shot path and the series path identically (always iterate).
    """
    if not tokens:
        return [tokens]
    series, skeleton = _find_series_params(tokens)
    if not series:
        return [tokens]

    # Preserve the order params first appear in the input so the operator can read the expansion.
    seen = []
    keys_in_order = []
    for tok in skeleton:
        if isinstance(tok, tuple) and tok[0] == "__series__":
            if tok[1] not in seen:
                keys_in_order.append(tok[1])
                seen.append(tok[1])

    # Cartesian product — itertools.product would do this, but writing it out keeps the diagnostic
    # (which combination failed) trivial to attach, and the typical sweep is small (<100 combos).
    combos = [{}]
    for key in keys_in_order:
        new_combos = []
        for partial in combos:
            for val in series[key]:
                c = dict(partial)
                c[key] = val
                new_combos.append(c)
        combos = new_combos

    # Materialize each combination into a real token list by replacing the series placeholders.
    results = []
    for combo in combos:
        out = []
        for tok in skeleton:
            if isinstance(tok, tuple) and tok[0] == "__series__":
                out.append(combo[tok[1]])
            else:
                out.append(tok)
        results.append(out)
    return results


def describe_combination(tokens):
    """One-line label of an expanded amc token list — used in the run log + filename suffix so each
    render in a series is distinguishable. Mirrors the recipe style of engine._config_to_recipe but
    operates on tokens (pre-build), so it works for both the CLI and TUI paths."""
    parts = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in SERIES_PARAMS and i + 1 < len(tokens) and not isinstance(tokens[i + 1], tuple):
            parts.append(f"{tok}{tokens[i+1]}")
            i += 2
            continue
        i += 1
    return "_".join(parts) if parts else "single"


def apply_amc_to_state(state, tokens):
    """Apply a subset of amc tokens to a SessionState-like object (TUI) — the series-eligible params.

    The CLI's ``SampleCutter.config_automix`` builds an ``AutoMixerConfig`` directly; the TUI's
    ``engine.build_config`` reads from ``SessionState``, so the TUI series runner needs an
    equivalent applier that maps amc tokens onto ``state.*`` fields. Only the params declared
    sweepable in ``SERIES_PARAMS`` are handled — the TUI's panels remain the surface for the rest
    (multitrack, snap/nofill flags, etc.) and stay constant across a series.

    Mutates ``state`` in place and returns it, so callers can chain ``apply_amc_to_state(copy, …)``.
    Unknown / unsupported tokens are silently skipped — a series tokens-list only ever contains the
    expanded sweepable params plus whatever non-bracketed constants the operator wrote alongside,
    so a stray token is a non-action rather than a crash.
    """
    i = 0
    while i < len(tokens):
        key = tokens[i]
        # Two-token forms: key + value.
        if key in ("l", "s", "ss", "w", "m", "ek", "en", "sw", "fg", "lk", "seed") \
                and i + 1 < len(tokens):
            val = tokens[i + 1]
            if key == "l":
                # Match the CLI: ``l <int>`` absolute ms; ``l /N`` and ``l *N`` transform current.
                base = getattr(state, "sample_length_ms", 0) or 0
                try:
                    if val.startswith("/"):
                        state.sample_length_ms = max(1, int(round(base / float(val[1:]))))
                    elif val.startswith("*"):
                        state.sample_length_ms = max(1, int(round(base * float(val[1:]))))
                    else:
                        state.sample_length_ms = max(1, int(round(float(val))))
                except (ValueError, ZeroDivisionError):
                    pass
            elif key == "s":
                try:
                    state.speed = float(val)
                except ValueError:
                    pass
            elif key == "ss":
                try:
                    state.sample_speed = float(val)
                except ValueError:
                    pass
            elif key == "w":
                try:
                    state.window_divider = int(float(val))
                except ValueError:
                    pass
            elif key == "m":
                state.mode = val
            elif key == "ek":
                try:
                    state.euclid_k = int(val)
                except ValueError:
                    pass
            elif key == "en":
                try:
                    state.euclid_n = int(val)
                except ValueError:
                    pass
            elif key == "sw":
                try:
                    state.swing = float(val)
                except ValueError:
                    pass
            elif key == "fg":
                try:
                    state.fill_gain_db = float(val)
                except ValueError:
                    pass
            elif key == "lk":
                try:
                    state.lib_clusters = int(val)
                except ValueError:
                    pass
            elif key == "seed":
                # SessionState does not carry seed today (CLI-only); set it as a plain attribute so
                # ``build_config`` can read it via getattr if/when seed is wired into the TUI.
                try:
                    setattr(state, "seed", int(val))
                except ValueError:
                    pass
            i += 2
            continue
        if key == "lib" and i + 1 < len(tokens):
            # lib sim|con — the policy word.
            p = tokens[i + 1]
            state.lib_policy = "contrast" if p.startswith("con") else "similarity"
            i += 2
            continue
        i += 1
    return state
