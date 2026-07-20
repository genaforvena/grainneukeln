def log_message(logger, message):
    if logger:
        logger.info(message)
    else:
        print(message)

import random
import numpy as np


def apply_seed(config):
    """Seed Python's ``random`` + numpy's global RNG from ``config.seed`` when set.

    Called at the top of every mixer's ``mix()`` so a seeded config produces byte-identical output
    across runs (the bit-identity test contract). No-op when ``seed is None`` (legacy unseeded
    behaviour — runs differ as before). Also returns the value so ``LibraryAutoMixer`` can build a
    dedicated ``np.random.default_rng(seed)`` from the same source."""
    if getattr(config, "seed", None) is not None:
        random.seed(config.seed)
        np.random.seed(config.seed)
    return config.seed


def concat_bit_identical(segs):
    """Concatenate ``AudioSegment``s bit-identically to chained ``append(crossfade=0)``.

    Replaces the O(L²) ``out = out.append(seg, crossfade=0)`` pattern with a single ``b"".join`` of
    the underlying ``_data`` bytes + one ``_spawn`` on the first segment's attrs — O(total_bytes).
    Verified bit-identical against pydub 0.25.1's ``append`` (``audio_segment.py:1253-1254``):
    ``crossfade=0`` skips the crossfade branch entirely and returns ``seg1._spawn(seg1._data +
    seg2._data)``; chained calls compose as ``b"".join`` of every segment's ``_data``.

    The ``_sync`` that pydub's ``append`` performs is a no-op when all segments share attrs
    (frame_rate/sample_width/channels) — which is the case for every call site in the mixers (all
    grains derive from the same source via slice + band_pass, which preserve attrs; ``AudioSegment.
    silent`` defaults match a 16-bit mono 44100Hz source). An empty list returns ``AudioSegment.
    empty()`` to match the seed-empty-mix path."""
    from pydub import AudioSegment
    if not segs:
        return AudioSegment.empty()
    if len(segs) == 1:
        return segs[0]
    joined = b"".join(s._data for s in segs)
    return segs[0]._spawn(joined)


def overlay_bit_identical(canvas_ms, grains_at_pos, frame_rate, sample_width=2, channels=1):
    """Build an ``AudioSegment`` by overlaying grains at positions — bit-identical to chained
    ``out = out.overlay(grain, position=p)`` on a starting-silent canvas.

    Replaces the O(L²) pydub-overlay pattern (each call walks the FULL output buffer including the
    unchanged prefix and tail) with a pre-allocated numpy int16 canvas + per-grain saturating-add
    into the overlap slice only. For a 30s canvas with 2000 grains this is the dominant cost
    difference: pydub does ~2000 × 30s × 44100 × 2 bytes ≈ 5 GB of redundant walks; the canvas does
    ~2000 × grain_len bytes ≈ a few MB of work.

    Bit-identity: pydub's ``overlay`` (``audio_segment.py:1174-1248``) reduces (for our usage —
    ``times=1``, ``gain_during_overlay=None``) to ``audioop.add(canvas[p:p+gL]._data, grain._data,
    sample_width)`` in the overlap slice, with unchanged bytes outside. ``audioop.add`` for
    sample_width=2 is a C-level SATURATING int16 add: int16 → int32 sum, clipped to [-32768, 32767].
    The numpy replication here (``np.clip(a.astype(int32) + b.astype(int32), -32768,
    32767).astype(int16)``) is bit-identical — verified against CPython 3.12's ``audioop`` C source
    and the ``test_bit_identity`` fixtures.

    The caller MUST pass canvas attrs (frame_rate/sample_width/channels) that match what pydub's
    ``_sync`` would have produced on (``AudioSegment.silent()`` canvas defaults = 11025 Hz / 2 / 1,
    source-grafted grains). ``_sync`` picks ``max`` across segments (``audio_segment.py:_sync``),
    so the canvas attrs are ``max(11025, source_fr) / max(2, source_sw) / max(1, source_ch)`` — in
    practice the source's attrs (real audio is ≥ 11025 Hz). The mixers pass the source's attrs
    directly, which matches for every real source; the fixture source (44100/2/1) and any standard
    mp3 also match.

    Order matters when grains overlap (saturation is non-associative), so the caller MUST pass the
    grains in the same order pydub would have applied them — the mixers do (sequential ``for`` loops).

    Args:
        canvas_ms: length of the silent starting canvas, in milliseconds.
        grains_at_pos: iterable of ``(position_ms_int, AudioSegment)``. Grains must already be at
            the canvas's attrs (the mixers' ``_create_grain`` paths produce source-attr grains, and
            the canvas is sized to match — see the note above).
        frame_rate / sample_width / channels: the canvas's attrs. MUST be ``max(11025, source_fr)``
            etc. (what pydub's ``_sync`` would produce).

    Returns:
        ``AudioSegment`` of the canvas with every grain mixed in, byte-identical to the chained-
        overlay result.
    """
    from pydub import AudioSegment

    n_samples = int(canvas_ms * frame_rate / 1000) * channels
    canvas_np = np.zeros(n_samples, dtype=np.int16)

    for position_ms, grain in grains_at_pos:
        if grain is None or len(grain) == 0:
            continue
        g_samples = np.frombuffer(grain._data, dtype=np.int16)
        # ms → sample index (mono: 1 sample/ms × frame_rate/1000; the channels multiplier is already
        # in n_samples and g_samples, so a single ms-to-frame conversion covers both).
        p = int(position_ms) * channels * frame_rate // 1000
        end = min(p + len(g_samples), n_samples)
        n = end - p
        if n <= 0:
            continue
        # Saturating add (clip on overflow) — exactly audioop.add for sample_width=2.
        canvas_np[p:end] = np.clip(
            canvas_np[p:end].astype(np.int32) + g_samples[:n].astype(np.int32),
            -32768, 32767,
        ).astype(np.int16)

    return AudioSegment(
        canvas_np.tobytes(),
        frame_rate=frame_rate,
        sample_width=sample_width,
        channels=channels,
    )


def calculate_step(beats):
    """Calculate the step size based on the beats."""
    if len(beats) == 0 or np.all(beats <= 0):
        return 1
    return max(1, int(np.mean(beats) / 4))


def beat_grid_floor(beat_positions, duration_ms, grid_period_ms=500, min_beats=4):
    """Floor a degenerate onset detection to a uniform beat grid.

    ``librosa.beat_track`` locks a SINGLE beat onto ambient/beatless material — a note3
    room recording, speech — where there is no rhythmic pulse to find. The rw
    (RandomWindow) mixer places one window per detected beat, so a 1-beat read collapses
    an 11.8s source to a ~0.2s grind that the downstream hollow gate then rejects (the
    mesh-sound-reflex ``skip:hollow`` storm of 2026-07-20 — every 1-beat note3 record,
    ~25% of the batch). This is the same 'rhythm-seeking regime' the poly/library mixers
    already embrace: beatless input still grinds, on a hallucinated grid. When fewer than
    ``min_beats`` beats are found, replace them with an evenly-spaced grid spanning the
    whole source so the mix covers it; genuinely rhythmic input (>= ``min_beats``) is
    returned untouched. A source too short to hold two grid slots is left alone.

    ``min_beats=4`` is the observed cliff: a 1-beat read grinds to 0.2s (hollow), a 4-beat
    read to ~1.7s (clears the >=1s gate on its own), so only 1-3 beat collapses are floored.
    """
    beats = np.asarray(beat_positions)
    if len(beats) >= min_beats:
        return beats
    if duration_ms < grid_period_ms * 2:
        return beats
    return np.arange(0, int(duration_ms), int(grid_period_ms)).astype(int)


def beat_interval(beats):
    """The real beat PERIOD in ms — the base value for grain length (``l = beat``).

    ``beats`` are cumulative beat POSITIONS (ms), so the period is the SPACING between
    consecutive beats, not their mean. (``calculate_step`` above takes ``mean(beats)/4``,
    which — since beats are positions — is a quarter of the mean *position*, i.e. roughly
    an eighth of the track length, and has nothing to do with the beat. That is why
    dividing it by 2/3 never produced a musical subdivision.) ``median(diff)`` is robust to
    detector jitter and the odd dropped/double beat. Returns 0 when the beat is unknowable
    (< 2 beats), so the caller can fall back.
    """
    beats = np.asarray(beats)
    if len(beats) < 2:
        return 0
    diffs = np.diff(beats)
    diffs = diffs[diffs > 0]
    if len(diffs) == 0:
        return 0
    return max(1, int(round(float(np.median(diffs)))))
