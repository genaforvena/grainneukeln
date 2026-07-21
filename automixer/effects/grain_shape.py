"""Per-grain shaping effects: probability-gated reverse playback and an attack/release envelope.

Both operate on one already-cut grain (a pydub ``AudioSegment``). There is no single shared
mixer loop to hook these into once -- rw/q/poly/lib each build grains their own way -- so this
module holds the two primitives and every mixer calls them at the point it already has a
finished grain in hand (design doc 2026-07-21).
"""


def grain_shape_params(config):
    """Read ``(reverse_prob, env_pct)`` off a mixer config with the same defaults
    ``AutoMixerConfig`` itself uses, via ``getattr`` so a config built without them (e.g. a bare
    test fixture) still works. Shared by all 4 mixers so the defaults live in exactly one place."""
    return (
        float(getattr(config, "reverse_prob", 0.0)),
        float(getattr(config, "env_pct", 8.0)),
    )


def maybe_reverse(seg, prob, rng):
    """Reverse ``seg`` with probability ``prob`` (0..1), decided by ``rng.random()``.

    ``rng`` MUST be whatever RNG source the calling mixer already threads through
    ``apply_seed``/``np.random.default_rng`` (never a fresh unseeded call) -- both the stdlib
    ``random`` module and an ``np.random.Generator`` instance expose a no-arg ``.random()`` in
    [0, 1), so either can be passed here and the seed-reproducibility contract (same seed + params
    -> byte-identical output) holds either way. ``prob <= 0`` short-circuits without touching the
    RNG at all, so a `reverse_prob=0.0` render draws exactly as many random numbers as before this
    feature existed.
    """
    if prob <= 0 or len(seg) == 0:
        return seg
    if rng.random() < prob:
        return seg.reverse()
    return seg


def apply_envelope(seg, pct):
    """Attack/release fade, ``pct`` percent of the segment's own length tapered on each edge.

    ``pct <= 0`` is a no-op (the explicit opt-out, `amc env 0`) -- otherwise this runs
    unconditionally for every mixer, since a hard-cut grain boundary is a defect (audible click),
    not a creative choice. The taper is clamped to at most half the grain's length so an
    oversized ``pct`` can never make attack and release overlap/exceed the grain.
    """
    if pct <= 0 or len(seg) == 0:
        return seg
    taper_ms = int(len(seg) * (pct / 100.0))
    taper_ms = max(0, min(taper_ms, len(seg) // 2))
    if taper_ms <= 0:
        return seg
    return seg.fade_in(taper_ms).fade_out(taper_ms)
