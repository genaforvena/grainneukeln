"""Quantized macro-granular mixer (issue #5) — mode ``"q"``.

Where ``RandomWindowAutoMixer`` picks a *random* beat per grain and concatenates window-chunks end to
end (so *which* grain lands *where* is random), this mixer places grains on an explicit **euclidean
beat-subdivision grid** and cuts each grain at a source **onset**:

- The beat period is subdivided into ``n`` slots (``slot = beat_period / n``) and a grain fires only on
  the slots the euclidean pattern ``E(k, n)`` marks — a *designed* groove (tresillo, cinquillo, ...)
  rather than a uniform fill. Placement is deterministic given (beats, k, n).
- Each grain is cut at a ``librosa.onset.onset_detect`` transient, snapped to the nearest grid slot, so
  the grain is a musically meaningful unit rather than an arbitrary window. The *choice* of which onset
  feeds each slot is random — so two runs differ in content while the grid stays put.

No beat floor (README's rhythm-seeking regime): librosa hallucinates a pulse on beatless input and
cannot report "no rhythm", so a beatless source still grinds on the hallucinated grid; only when the
beat is genuinely unknowable (< 2 beats) do we fall back to the grain length as the slot period.

Gap-fill (operator 2026-07-18): the euclidean pattern marks only k of n slots as HITS; the n-k REST
slots were left silent, so a sparse groove (E(3,8): 5 of 8 slots silent) rendered very *choppy*
("обрывисто"). We now FILL the rest slots with grains cut from **off-grid remnant** material — the
audio *between* the snapped grid onsets, i.e. the pieces that did NOT land in a quantum — at a
reduced gain (``fill_gain_db``, default -6) so the euclidean HITS still read as the accented groove
instead of a uniform wash. Default on (``config.fill``); ``nofill`` restores the pure-grid behaviour.
The grid-miss remnants are stitched into the pauses, not discarded.
"""
import random

from pydub import AudioSegment
from tqdm import tqdm

from automixer.effects.band_pass import band_pass_filer
from automixer.effects.change_tempo import change_audioseg_tempo, snap_to_length
from automixer.effects.grain_shape import maybe_reverse, apply_envelope
from automixer.effects.groove import swing_offset
from automixer.iterators.grid import euclidean, grid_slots
from automixer.iterators.onsets import onset_positions
from automixer.utils import beat_interval, apply_seed, overlay_bit_identical


class QuantizedAutoMixer:
    def mix(self, config):
        apply_seed(config)
        audio = config.audio
        total_ms = len(audio)
        if total_ms == 0:
            return AudioSegment.empty()

        # Beat period -> slot grid. beat_interval returns 0 when the beat is unknowable (< 2 beats);
        # fall back to the grain length (never reject — no beat floor).
        beat_period = beat_interval(config.beats)
        if beat_period <= 0:
            beat_period = config.sample_length if config.sample_length and config.sample_length > 0 else 500.0

        k = int(getattr(config, "euclid_k", 3))
        n = int(getattr(config, "euclid_n", 8))
        pattern = euclidean(k, n)
        if not pattern:
            pattern = [1]
            n = 1
        slot_ms = float(beat_period) / n
        grain_len = max(1, int(round(slot_ms)))

        slots = grid_slots(beat_period, pattern, total_ms)
        onsets = self._onsets(audio, slot_ms)

        # Placement effects (issue #8): swing/groove micro-timing + pitch-preserving snap.
        swing = float(getattr(config, "swing", 0) or 0)
        template = getattr(config, "groove_template", None)
        snap = bool(getattr(config, "snap", False))

        # Gap-fill (operator 2026-07-18): stitch off-grid remnants into the REST slots instead of
        # leaving silence. Default on; fills sit `fill_gain_db` below the hits so the groove reads.
        fill = bool(getattr(config, "fill", True))
        fill_gain_db = float(getattr(config, "fill_gain_db", -6.0))
        num_slots = int(total_ms // slot_ms) if slot_ms > 0 else 0
        hit_idx = {i for i in range(num_slots) if pattern[i % n]}
        remnants = self._remnants(onsets, len(audio), grain_len) if fill else []

        # Canvas must be long enough to hold swung-late off-beats and the trailing grain.
        canvas_ms = int(round(total_ms + slot_ms + grain_len))
        # Precompute the per-pool candidate sets ONCE — the per-grain O(n_onsets) filter
        # ``[o for o in onsets if 0 <= o <= max_start]`` used to run inside ``_create_grain`` every
        # call, but max_start is fixed for the mix (it depends only on len(audio) and grain_len),
        # so the same list was being rebuilt ~2 × num_slots times. Bit-identical (same list, same
        # random.choice draws); only the call site moves up. The remnants pool filters the same way.
        max_start = len(audio) - grain_len
        onset_candidates = [o for o in onsets if 0 <= o <= max_start]
        remnant_candidates = [o for o in remnants if 0 <= o <= max_start] if fill else []
        # Collect (position_ms, grain) pairs from BOTH the euclidean-hit loop and the gap-fill loop
        # into one list, then overlay onto a numpy canvas ONCE at the end. Bit-identical to the
        # pre-refactor chained ``out = out.overlay(grain, position=p)`` because pydub's overlay
        # reduces to ``audioop.add`` (saturating int16 add) in the overlap slice, replicated exactly
        # by ``overlay_bit_identical``; order is preserved (hits applied before fills, same as
        # before). Pre-refactor every overlay call walked the FULL canvas (the unchanged prefix and
        # tail too) → O(canvas × grains); now O(grain_len × grains).
        grains_at_pos = []
        pbar = tqdm(desc="Quantizing", total=len(slots))
        for pos in slots:
            slot_idx = int(round(pos / slot_ms)) if slot_ms > 0 else 0
            if template:
                offset = float(template[slot_idx % len(template)])
            else:
                offset = swing_offset(slot_idx, swing, slot_ms)
            grain = self._create_grain(config, onsets, grain_len, snap, candidates=onset_candidates)
            if grain is not None and len(grain) > 0:
                grains_at_pos.append((int(round(pos + offset)), grain))
            pbar.update(1)
        pbar.close()

        # Fill the REST slots (the n-k the euclidean pattern leaves silent) with quieter off-grid
        # remnant grains, so a sparse groove is textured rather than choppy — grid-miss material
        # stitched into the pauses, not discarded.
        if fill and num_slots:
            for i in range(num_slots):
                if i in hit_idx:
                    continue
                pos = i * slot_ms
                if template:
                    offset = float(template[i % len(template)])
                else:
                    offset = swing_offset(i, swing, slot_ms)
                grain = self._create_grain(
                    config, remnants, grain_len, snap, candidates=remnant_candidates,
                )
                if grain is not None and len(grain) > 0:
                    # apply_gain is applied BEFORE collection so the fill grain's bytes are already
                    # attenuated when mixed into the canvas — same order pydub's overlay would see.
                    grains_at_pos.append((int(round(pos + offset)), grain.apply_gain(fill_gain_db)))

        # Canvas attrs = max(silent defaults, source attrs) — what pydub's _sync lands on after the
        # first overlay. For real sources (≥11025 Hz) this equals the source's attrs.
        return overlay_bit_identical(
            canvas_ms, grains_at_pos,
            frame_rate=max(11025, audio.frame_rate),
            sample_width=max(2, audio.sample_width),
            channels=max(1, audio.channels),
        )

    def _remnants(self, onsets, audio_len, grain_len):
        """Off-grid remnant cut positions: the MIDPOINTS between consecutive snapped onsets — the
        material that fell *between* the grid quanta and would otherwise be discarded. These feed the
        rest-slot fills. Empty -> ``_create_grain`` falls back to a random (still off-grid) position."""
        pts = sorted({o for o in onsets if 0 <= o <= max(0, audio_len - grain_len)})
        rem = []
        for a, b in zip(pts, pts[1:]):
            mid = (a + b) // 2
            if mid != a and mid != b:
                rem.append(mid)
        return rem

    def _create_grain(self, config, onsets, grain_len, snap=False, candidates=None):
        """Cut one grain at a (randomly chosen) source position from ``onsets`` (an onset pool for
        HIT slots, or a remnant pool for fills), band-passed per channel.

        Random pick -> content varies run to run; the grid position it lands on is fixed by the
        caller, so the *placement* stays deterministic (issue #5 acceptance #4).

        ``candidates`` is the precomputed subset of ``onsets`` satisfying ``0 <= o <= max_start``
        — passed in by the caller (``mix``) so the per-grain O(n_onsets) list comprehension runs
        ONCE per mix, not once per grain. Bit-identical to computing it here (same list, same
        ``random.choice`` draw); only the call site moves. ``None`` falls back to the in-function
        filter for callers that didn't precompute (e.g. tests)."""
        audio = config.audio
        max_start = len(audio) - grain_len
        if max_start <= 0:
            return audio[:grain_len]

        if candidates is None:
            candidates = [o for o in onsets if 0 <= o <= max_start]
        if candidates:
            start_cut = random.choice(candidates)
        else:
            # No onset survived (silent/degenerate source): fall back to a random position rather
            # than a beat floor, so the grid still fills.
            start_cut = random.randint(0, max_start)

        # Snap (issue #8): cut the natural transient unit (onset -> next onset, capped) and
        # pitch-preservingly stretch it to the slot length, so off-length material lands on the grid.
        cut_len = grain_len
        if snap and candidates:
            nexts = [o for o in onsets if o > start_cut]
            raw = (nexts[0] - start_cut) if nexts else grain_len
            cut_len = int(max(1, min(raw, len(audio) - start_cut)))
            cut_len = int(max(grain_len * 0.5, min(grain_len * 1.5, cut_len)))

        reverse_prob = float(getattr(config, "reverse_prob", 0.0))
        env_pct = float(getattr(config, "env_pct", 8.0))
        grain = AudioSegment.silent(duration=cut_len)
        for channel in config.channels_config:
            channel_chunk = audio[start_cut: start_cut + cut_len]
            channel_chunk = maybe_reverse(channel_chunk, reverse_prob, random)
            if not channel.bypass:
                channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
            grain = grain.overlay(channel_chunk)
        if snap and len(grain) != grain_len:
            grain = snap_to_length(grain, grain_len, verbose=config.is_verbose_mode_enabled)
        if config.sample_speed != 1.0:
            grain = change_audioseg_tempo(grain, config.sample_speed,
                                          verbose=config.is_verbose_mode_enabled)
        grain = apply_envelope(grain, env_pct)
        return grain

    def _onsets(self, audio, slot_ms):
        """Source onset positions (ms), snapped to the nearest grid slot — see
        ``automixer.iterators.onsets.onset_positions``."""
        return onset_positions(audio, snap_ms=slot_ms)
