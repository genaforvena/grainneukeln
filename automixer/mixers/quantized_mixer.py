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
"""
import random

from pydub import AudioSegment
from tqdm import tqdm

from automixer.effects.band_pass import band_pass_filer
from automixer.effects.change_tempo import change_audioseg_tempo, snap_to_length
from automixer.effects.groove import swing_offset
from automixer.iterators.grid import euclidean, grid_slots
from automixer.iterators.onsets import onset_positions
from automixer.utils import beat_interval


class QuantizedAutoMixer:
    def mix(self, config):
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

        # Canvas must be long enough to hold swung-late off-beats and the trailing grain.
        canvas_ms = int(round(total_ms + slot_ms + grain_len))
        out = AudioSegment.silent(duration=canvas_ms)
        pbar = tqdm(desc="Quantizing", total=len(slots))
        for pos in slots:
            slot_idx = int(round(pos / slot_ms)) if slot_ms > 0 else 0
            if template:
                offset = float(template[slot_idx % len(template)])
            else:
                offset = swing_offset(slot_idx, swing, slot_ms)
            grain = self._create_grain(config, onsets, grain_len, snap)
            if grain is not None and len(grain) > 0:
                out = out.overlay(grain, position=int(round(pos + offset)))
            pbar.update(1)
        pbar.close()
        return out

    def _create_grain(self, config, onsets, grain_len, snap=False):
        """Cut one grain at a (randomly chosen) source onset, band-passed per channel.

        Random onset -> content varies run to run; the grid position it lands on is fixed by the
        caller, so the *placement* stays deterministic (issue #5 acceptance #4)."""
        audio = config.audio
        max_start = len(audio) - grain_len
        if max_start <= 0:
            return audio[:grain_len]

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

        grain = AudioSegment.silent(duration=cut_len)
        for channel in config.channels_config:
            channel_chunk = audio[start_cut: start_cut + cut_len]
            channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
            grain = grain.overlay(channel_chunk)
        if snap and len(grain) != grain_len:
            grain = snap_to_length(grain, grain_len, verbose=config.is_verbose_mode_enabled)
        if config.sample_speed != 1.0:
            grain = change_audioseg_tempo(grain, config.sample_speed,
                                          verbose=config.is_verbose_mode_enabled)
        return grain

    def _onsets(self, audio, slot_ms):
        """Source onset positions (ms), snapped to the nearest grid slot — see
        ``automixer.iterators.onsets.onset_positions``."""
        return onset_positions(audio, snap_ms=slot_ms)
