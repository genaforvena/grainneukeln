"""Cyclic pattern engine — named timelines, explicit patterns, additive meters, accent maps.

`grid.euclidean` can only say "k hits spread as evenly as the integers allow". That covers a
tresillo and a four-on-the-floor, and it covers the West African standard bell only by accident
(it *is* E(7,12), at the right rotation). It cannot express a son clave, a teental theka, or a
9/8 aksak — and it has no vocabulary at all for the thing most Asian and African percussion
traditions actually carry the groove in: **which strokes are accented**, not merely which slots
are struck. A teental theka strikes all sixteen matras; what makes it teental is the sam on 1 and
the *khali* (open, unaccented) at 9.

Three things this module adds on top of the euclidean grid:

- ``pat`` — an explicit cycle. A named timeline (``pat bembe``), an ``x..x..x.`` / ``10010010``
  string, or an additive meter ``+2,2,2,3`` (the 9/8 aksak — hits at each group head).
- ``cyc`` — how many BEATS one cycle of the pattern spans. The euclidean grid hardcoded one beat
  per cycle, which is right for an 8-slot tresillo and badly wrong for a 16-slot clave (crammed
  into a single beat it is a 25 ms blur, not a clave). A 16-pulse clave wants ``cyc 4``.
- ``rot`` / ``acc`` — rotation (the clave/bell family is largely one cycle at different
  rotations) and a per-slot gain map in dB (the accent structure). Rotation moves the accent map
  WITH the pattern; a sam left behind by a rotation lands on the wrong stroke.

**On the named library:** each entry is a *reduction* — the timeline, clap pattern, or theka
skeleton of a tradition, not a transcription of a performance. `teental` is the theka's accent
skeleton, not a tabla solo; `colotomic` is the Javanese kenong/kempul punctuation, not a gamelan
piece. They are starting points that put the grid in the right metric universe for the source
material, which is exactly what a grinder fed a djembe recording needs.
"""

HIT_CHARS = "xX1#o"
REST_CHARS = ".-_0"
IGNORE_CHARS = " \t|,;"


class PatternError(ValueError):
    """Raised for a `pat`/`acc` spec that cannot be read as a cycle — never silently defaulted.

    A pattern that quietly falls back to the euclidean default is the silent-fallback trap: the
    render still sounds plausible, and nothing tells you the clave you asked for never arrived.
    """


# name -> {pat, cyc (beats per cycle), acc (dB per slot, cycled), note (tradition)}
#
# `acc` convention: 0 dB is the full-strength stroke; negatives duck. A map shorter than the
# pattern is cycled over it (so a 3-value triplet map covers a 12-pulse cycle).
NAMED_PATTERNS = {
    # ---- West / Central Africa + the diaspora timelines --------------------------------------
    "tresillo": {"pat": "x..x..x.", "cyc": 2,
                 "note": "3+3+2 — the ubiquitous West African / Cuban cell"},
    "cinquillo": {"pat": "x.xx.xx.", "cyc": 2,
                  "note": "the tresillo's filled-in 5-stroke cousin"},
    "bembe": {"pat": "x.xx.x.xx.x.", "cyc": 4, "acc": "0,-9,-5",
              "note": "the 7-stroke standard bell (Ewe/Yoruba 12/8) — E(7,12) at its "
                      "canonical rotation, accented on the triplet heads"},
    "bell6": {"pat": "x.xx.x", "cyc": 2,
              "note": "the short bell — the standard bell's 6-pulse cousin"},
    "clave32": {"pat": "x..x..x...x.x...", "cyc": 4,
                "note": "son clave, 3-2"},
    "clave23": {"pat": "..x.x...x..x..x.", "cyc": 4,
                "note": "son clave, 2-3 (clave32 rotated by half a cycle)"},
    "rumba32": {"pat": "x..x...x..x.x...", "cyc": 4,
                "note": "rumba clave, 3-2"},
    "bossa": {"pat": "x..x..x...x..x..", "cyc": 4,
              "note": "bossa-nova clave"},
    "shiko": {"pat": "x...x.x...x.x...", "cyc": 4,
              "note": "shiko bell (Nigeria)"},
    "soukous": {"pat": "x..x..x...xx....", "cyc": 4,
                "note": "soukous bell (Congo)"},
    "gnawa": {"pat": "xxxxxxxxxxxx", "cyc": 4, "acc": "0,-11,-8",
              "note": "qraqeb — a continuous 12/8 triplet stream carried entirely by accent"},
    "maqsum": {"pat": "xx.xx.x.", "cyc": 2, "acc": "0,-8,-8,-8,0,-8,-8,-8",
               "note": "Egyptian maqsum — DUM on 1 and 5, taks between"},

    # ---- South Asia — tala thekas (accent skeletons, all matras struck) ----------------------
    "teental": {"pat": "xxxxxxxxxxxxxxxx", "cyc": 4,
                "acc": "0,-8,-8,-8,-3,-8,-8,-8,-14,-11,-11,-11,-3,-8,-8,-8",
                "note": "tintal, 16 matras (4+4+4+4) — sam on 1, KHALI (open) at 9"},
    "jhaptal": {"pat": "xxxxxxxxxx", "cyc": 2.5,
                "acc": "0,-8,-3,-8,-8,-14,-11,-3,-8,-8",
                "note": "jhaptal, 10 matras (2+3+2+3) — khali at 6"},
    "rupak": {"pat": "xxxxxxx", "cyc": 1.75,
              "acc": "-12,-9,-9,0,-8,-3,-8",
              "note": "rupak, 7 matras (3+2+2) — begins on khali, sam is unaccented"},
    "keherwa": {"pat": "xxxxxxxx", "cyc": 2,
                "acc": "0,-8,-8,-8,-12,-8,-8,-8",
                "note": "keherwa, 8 matras (4+4) — khali at 5"},
    "dadra": {"pat": "xxxxxx", "cyc": 1.5,
              "acc": "0,-8,-8,-12,-8,-8",
              "note": "dadra, 6 matras (3+3)"},
    "adi": {"pat": "x...x.x.", "cyc": 2,
            "note": "Carnatic adi tala clap pattern, 8 aksharas (4+2+2)"},
    "khandachapu": {"pat": "x.x..", "cyc": 1.25,
                    "note": "Carnatic khanda chapu, 5 (2+3)"},
    "misrachapu": {"pat": "x..x.x.", "cyc": 1.75,
                   "note": "Carnatic misra chapu, 7 (3+2+2)"},

    # ---- Southeast / East / Central Asia -----------------------------------------------------
    "colotomic": {"pat": "x.x.x.x.x.x.x.x.", "cyc": 4,
                  "acc": "0,-14,-9,-14,-5,-14,-9,-14,-5,-14,-9,-14,-5,-14,-9,-14",
                  "note": "Javanese colotomic punctuation — gong on 1, kenong on the 4s, "
                          "kempul between"},
    "aksak9": {"pat": "+2,2,2,3", "cyc": 2.25,
               "note": "9/8 aksak (2+2+2+3) — Turkish/Uzbek/Balkan limping meter"},
    "aksak7": {"pat": "+2,2,3", "cyc": 1.75,
               "note": "7/8 aksak (2+2+3)"},
    "aksak5": {"pat": "+2,3", "cyc": 1.25,
               "note": "5/8 aksak (2+3)"},
    "jajinmori": {"pat": "x..x..x..x..", "cyc": 4,
                  "acc": "0,-12,-12,-6,-12,-12,-3,-12,-12,-6,-12,-12",
                  "note": "Korean 12/8 janggu cycle — four triplet groups, accent on 1 and 7"},
}


def additive(groups):
    """Additive (non-isochronous) meter: one hit at the head of each group.

    ``[2,2,2,3]`` -> ``x.x.x.x..`` — the 9/8 aksak. This is the metric shape Turkish, Uzbek and
    Balkan music is built from and the one thing a euclidean generator can never produce: the
    gaps are *deliberately uneven*, not as-even-as-the-integers-allow.
    """
    groups = [int(g) for g in groups]
    if not groups or any(g <= 0 for g in groups):
        raise PatternError(f"additive groups must all be >= 1, got {groups}")
    pattern = []
    for g in groups:
        pattern.append(1)
        pattern.extend([0] * (g - 1))
    return pattern


def parse_pattern(spec):
    """Read a `pat` value into a 0/1 slot list.

    Three forms, tried in order:
      - ``+2,2,2,3``       additive meter (see ``additive``)
      - a library name     (case-insensitive, e.g. ``bembe``, ``clave32``, ``teental``)
      - a slot string      ``x..x..x.`` / ``10010010``; ``x X 1 # o`` hit, ``. - _ 0`` rest,
                           and ``space | , ;`` are ignored so bars can be written out.
    """
    if isinstance(spec, (list, tuple)):
        pattern = [1 if v else 0 for v in spec]
        if not any(pattern):
            raise PatternError("pattern has no hits")
        return pattern

    raw = (spec or "").strip()
    if not raw:
        raise PatternError("empty pattern")

    if raw.startswith("+"):
        return additive([g for g in raw[1:].replace(";", ",").split(",") if g.strip()])

    named = NAMED_PATTERNS.get(raw.lower())
    if named is not None:
        return parse_pattern(named["pat"])

    pattern = []
    for ch in raw:
        if ch in IGNORE_CHARS:
            continue
        if ch in HIT_CHARS:
            pattern.append(1)
        elif ch in REST_CHARS:
            pattern.append(0)
        else:
            raise PatternError(
                f"unknown pattern {raw!r}: not a library name, and {ch!r} is not a slot "
                f"character (hits {HIT_CHARS!r}, rests {REST_CHARS!r}). "
                f"Known names: {', '.join(sorted(NAMED_PATTERNS))}")
    if not pattern:
        raise PatternError(f"pattern {raw!r} has no slots")
    if not any(pattern):
        raise PatternError(f"pattern {raw!r} has no hits — a silent cycle renders nothing")
    return pattern


def parse_accents(spec):
    """Read an `acc` value into a list of per-slot gains in dB (0 = full strength, negative ducks).

    ``"0,-8,-8,-8"`` -> ``[0.0, -8.0, -8.0, -8.0]``. A map shorter than the pattern is cycled
    over it by the caller, so ``acc 0,-9,-5`` covers a 12-pulse cycle as a triplet accent.
    """
    if isinstance(spec, (list, tuple)):
        return [float(v) for v in spec]
    raw = (spec or "").strip()
    if not raw:
        raise PatternError("empty accent map")
    out = []
    for tok in raw.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(float(tok))
        except ValueError:
            raise PatternError(f"accent map {raw!r}: {tok!r} is not a dB number")
    if not out:
        raise PatternError(f"accent map {raw!r} has no values")
    return out


def rotate(seq, r):
    """Rotate a slot list left by ``r`` (negative = right). ``rot 2`` on the bell starts the cycle
    two pulses in — how the clave/bell family generates its variants."""
    if not seq:
        return list(seq)
    r = int(r) % len(seq)
    return list(seq[r:]) + list(seq[:r])


def resolve_pattern(pat_spec, cyc=None, rot=0, acc=None):
    """The ONE resolver both the CLI (`amc pat …`) and the TUI call, so the two can never drift.

    Returns ``(pattern, cycle_beats, accents_or_None)`` with rotation already applied to BOTH the
    pattern and the accent map. Library defaults (``cyc``, ``acc``) fill in only where the caller
    passed nothing, so an explicit ``cyc``/``acc`` always wins.
    """
    pattern = parse_pattern(pat_spec)
    named = None
    if isinstance(pat_spec, str):
        named = NAMED_PATTERNS.get(pat_spec.strip().lower())

    if cyc is None and named is not None:
        cyc = named.get("cyc", 1.0)
    cycle_beats = float(cyc) if cyc is not None else 1.0
    if cycle_beats <= 0:
        raise PatternError(f"cyc must be > 0, got {cycle_beats}")

    acc_spec = acc if acc is not None else (named or {}).get("acc")
    accents = None
    if acc_spec is not None:
        accents = parse_accents(acc_spec)
        # Cycle a short map up to the pattern length BEFORE rotating, or a rotation would shear
        # the map against the pattern it is supposed to travel with.
        if len(accents) != len(pattern):
            accents = [accents[i % len(accents)] for i in range(len(pattern))]

    rot = int(rot or 0)
    if rot:
        pattern = rotate(pattern, rot)
        if accents is not None:
            accents = rotate(accents, rot)
    return pattern, cycle_beats, accents


def describe(name):
    """One-line human description of a named pattern (used by `amc pat list` and the TUI)."""
    entry = NAMED_PATTERNS.get((name or "").lower())
    if not entry:
        return None
    pat = parse_pattern(entry["pat"])
    glyphs = "".join("x" if v else "." for v in pat)
    hits = sum(pat)
    return (f"{name:<12} {glyphs:<18} {hits:>2}/{len(pat):<3} cyc {entry.get('cyc', 1)}"
            f"{'  acc' if entry.get('acc') else '     '}  {entry.get('note', '')}")
