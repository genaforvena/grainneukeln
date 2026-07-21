"""Polyphonic macro-granular mixer (issue #6) — mode ``"poly"``.

Where ``rw``/``q`` run a **single** grain stream (one thing at a time, concatenated), this mixer runs
**N parallel streams** at different subdivisions of the same beat grid and **overlays** them, so they
phase against each other (Reich "Piano Phase", but granular):

- Each stream has a ``ratio`` r — it fires r grains per beat (``beat_period / r`` apart). Two streams
  at ratios 3 and 4 give a 3-against-4 polyrhythm that coincides every ``LCM(3,4) = 12`` subdivisions
  and drifts out of phase in between.
- Each stream keeps its own grain length and band-pass channels, so the layers stay distinguishable.
- Grains are cut at source onsets (shared onset pass) and overlaid onto one silent canvas at their
  grid offsets — a genuine layer, not a concatenation.

No beat floor (README's rhythm-seeking regime): beatless input still grinds on the hallucinated grid;
< 2 beats falls back to the grain length as the beat period.
"""
import random
from functools import reduce
from math import gcd

from pydub import AudioSegment
from tqdm import tqdm

from automixer.effects.band_pass import band_pass_filer
from automixer.effects.change_tempo import change_audioseg_tempo
from automixer.effects.grain_shape import maybe_reverse, apply_envelope, grain_shape_params
from automixer.iterators.onsets import onset_positions
from automixer.utils import beat_interval, apply_seed, overlay_bit_identical, slice_source


def _lcm(a, b):
    return a * b // gcd(a, b)


class PolyphonicAutoMixer:
    def mix(self, config, return_streams=False):
        """Overlay N parallel grain streams. When ``return_streams`` is set, also return the list of
        per-stream ``AudioSegment``s (each stream rendered on its own canvas) — the honest artifact
        for verifying each stream's subdivision and their phasing without band-leakage guesswork."""
        apply_seed(config)
        audio = config.audio
        total_ms = len(audio)
        if total_ms == 0:
            return (AudioSegment.empty(), []) if return_streams else AudioSegment.empty()

        streams = getattr(config, "streams", None)
        if not streams:
            # Default 3-against-4, both streams full-band.
            streams = [{"ratio": 4}, {"ratio": 3}]

        beat_period = beat_interval(config.beats)
        if beat_period <= 0:
            beat_period = config.sample_length if config.sample_length and config.sample_length > 0 else 500.0

        ratios = [max(1, int(s.get("ratio", 1))) for s in streams]
        cycle = reduce(_lcm, ratios)  # subdivisions per beat where all streams realign
        sub_ms = float(beat_period) / cycle
        # One onset pass at the finest grid the streams share, reused by every stream.
        onsets = onset_positions(audio, snap_ms=sub_ms)

        canvas_fr = max(11025, audio.frame_rate)
        canvas_sw = max(2, audio.sample_width)
        canvas_ch = max(1, audio.channels)
        canvas_ms = int(round(total_ms))

        total_grains = sum(int(total_ms / (beat_period / r)) + 1 for r in ratios)
        pbar = tqdm(desc="Polyrhythm", total=total_grains)
        stream_segs = []
        for s, ratio in zip(streams, ratios):
            step_ms = float(beat_period) / ratio            # this stream's subdivision period
            grain_len = int(round(s.get("length") or step_ms))
            grain_len = max(1, grain_len)
            channels = s.get("channels") or config.channels_config
            # Precompute this stream's candidate set ONCE — grain_len is fixed within a stream, so
            # ``max_start = len(audio) - grain_len`` is too, and the per-grain O(n_onsets) filter
            # was rebuilding the same list every grain. Bit-identical (same list, same random.choice
            # draws); only the call site moves up.
            max_start = len(audio) - grain_len
            stream_candidates = [o for o in onsets if 0 <= o <= max_start] if max_start > 0 else []
            # Per-stream canvas: collect this stream's grains + positions, overlay once. Bit-identical
            # to chained ``seg.overlay(grain, position=p)`` on a silent canvas (same _sync + audioop.add
            # chain as the q mixer). Each grain here lands on this stream's own subdivision grid; the
            # phasing between streams comes from the final fold below.
            stream_grains = []
            pos = 0.0
            while pos < total_ms:
                grain = self._create_grain(config, onsets, grain_len, channels,
                                           candidates=stream_candidates)
                if grain is not None and len(grain) > 0:
                    stream_grains.append((int(round(pos)), grain))
                pos += step_ms
                pbar.update(1)
            stream_segs.append(overlay_bit_identical(
                canvas_ms, stream_grains,
                frame_rate=canvas_fr, sample_width=canvas_sw, channels=canvas_ch,
            ))
        pbar.close()

        # Final fold: overlay every stream's full canvas onto a master canvas. Same helper; the
        # stream_segs are now full-canvas-length AudioSegments, so each "grain" in this fold is
        # stream-length and positioned at 0. Bit-identical to chained ``out.overlay(seg)``.
        fold_pairs = [(0, seg) for seg in stream_segs]
        out = overlay_bit_identical(
            canvas_ms, fold_pairs,
            frame_rate=canvas_fr, sample_width=canvas_sw, channels=canvas_ch,
        )
        return (out, stream_segs) if return_streams else out

    def _create_grain(self, config, onsets, grain_len, channels, candidates=None):
        """Cut one grain at a random source onset, band-passed through this stream's channels.

        Random onset -> content varies run to run; the stream's grid positions are fixed, so the
        polyrhythmic PLACEMENT is deterministic.

        ``candidates`` is the precomputed subset of ``onsets`` satisfying ``0 <= o <= max_start``
        — passed by the caller (``mix``) so the per-grain O(n_onsons) filter runs ONCE per stream,
        not once per grain. Bit-identical to in-function filtering; ``None`` falls back for callers
        that didn't precompute."""
        audio = config.audio
        max_start = len(audio) - grain_len
        if max_start <= 0:
            return audio[:grain_len]

        if candidates is None:
            candidates = [o for o in onsets if 0 <= o <= max_start]
        start_cut = random.choice(candidates) if candidates else random.randint(0, max_start)

        reverse_prob, env_pct = grain_shape_params(config)
        # Reverse is a property of the GRAIN, not of any one channel/band: the decision is drawn
        # ONCE here (on the primary-source slice) and never re-drawn inside the loop, or a
        # multi-band config could reverse one band while leaving another forward, scrambling
        # what's meant to be a single coherent grain. Dual-source grinding (2026-07-21): a channel
        # in this stream may pull its own slice from a DIFFERENT source (``slice_source``, when
        # tagged ``source2=True``), so the decision can no longer be reused as one shared
        # ``AudioSegment`` -- ``reversed_grain`` captures that same one-per-grain decision,
        # applied to whichever bytes each channel actually cuts.
        # (Review finding 2 considered replacing this with a length-only reverse draw to skip
        # the throwaway ``primary_slice`` copy, but tests/test_poly_mixer.py patches
        # ``maybe_reverse`` directly to assert the once-per-grain contract
        # (``test_reverse_decision_drawn_once_per_grain_not_per_channel``,
        # ``test_reverse_prob_one_reverses_every_grain``) -- removing the call breaks that
        # contract test, so the minor waste is kept rather than risk it.)
        primary_slice = audio[start_cut: start_cut + grain_len]
        base_chunk = maybe_reverse(primary_slice, reverse_prob, random)
        reversed_grain = base_chunk is not primary_slice
        grain = AudioSegment.silent(duration=grain_len)
        for channel in channels:
            channel_chunk = slice_source(config, channel, start_cut, grain_len)
            if reversed_grain:
                channel_chunk = channel_chunk.reverse()
            if not channel.bypass:
                channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
            grain = grain.overlay(channel_chunk)
        if config.sample_speed != 1.0:
            grain = change_audioseg_tempo(grain, config.sample_speed,
                                          verbose=config.is_verbose_mode_enabled)
        grain = apply_envelope(grain, env_pct)
        return grain
