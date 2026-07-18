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
from automixer.effects.change_tempo import change_audioseg_tempo
from automixer.iterators.grid import euclidean, grid_slots
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

        out = AudioSegment.silent(duration=int(round(total_ms)))
        pbar = tqdm(desc="Quantizing", total=len(slots))
        for pos in slots:
            grain = self._create_grain(config, onsets, grain_len)
            if grain is not None and len(grain) > 0:
                out = out.overlay(grain, position=int(round(pos)))
            pbar.update(1)
        pbar.close()
        return out

    def _create_grain(self, config, onsets, grain_len):
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

        grain = AudioSegment.silent(duration=grain_len)
        for channel in config.channels_config:
            channel_chunk = audio[start_cut: start_cut + grain_len]
            channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
            grain = grain.overlay(channel_chunk)
        if config.sample_speed != 1.0:
            grain = change_audioseg_tempo(grain, config.sample_speed,
                                          verbose=config.is_verbose_mode_enabled)
        return grain

    def _onsets(self, audio, slot_ms):
        """Source onset positions (ms), snapped to the nearest grid slot.

        Snapping quantizes the cut boundaries to the same grid the grains are placed on, so a grain
        is a transient *and* metrically aligned. Returns [] when nothing latches (the caller then
        falls back to a random position — never a beat floor)."""
        import numpy as np
        import librosa

        samples = np.array(audio.get_array_of_samples()).astype(np.float32)
        if audio.channels == 2:
            samples = samples.reshape((-1, 2)).mean(axis=1)
        peak = np.max(np.abs(samples)) if samples.size else 0.0
        if peak > 0:
            samples = samples / peak
        sr = audio.frame_rate
        try:
            onset_times = librosa.onset.onset_detect(y=samples, sr=sr, units="time")
        except Exception:
            return []
        if slot_ms <= 0:
            return sorted({int(round(t * 1000)) for t in onset_times})
        snapped = {int(round(round((t * 1000) / slot_ms) * slot_ms)) for t in onset_times}
        return sorted(s for s in snapped if s >= 0)
