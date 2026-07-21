"""quantized mixer (issue #5): grains land on a euclidean beat-subdivision grid.

Zero-dep on purpose — this repo has no test runner. Run it directly:

    PYTHONPATH=. .venv/bin/python tests/test_quantized_mixer.py

Verification principle (CLAUDE.md): the artifact, not the assertion. Every gate below RENDERS a
mix and reads the grain-start timestamps back out of the rendered audio (pydub.detect_nonsilent) —
never from an internal log the mixer could forge. The euclidean groove has to be *audible in the
bytes*: on a 400 ms click track with E(3,8) the grain starts must fall on the tresillo grid
(gaps 150,150,100 ms repeating), beatless input must still produce a non-empty mix, and the grid
must be deterministic across runs while the grain CONTENT varies.
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from pydub import AudioSegment
from pydub.generators import Sine, WhiteNoise
from pydub.silence import detect_nonsilent

from automixer.config import AutoMixerConfig, ChannelConfig
from automixer.mixers.quantized_mixer import QuantizedAutoMixer
from automixer.iterators.grid import euclidean

failures = []


def click_track(period_ms=400, n_clicks=5):
    """A crisp click track: a 5 ms 1 kHz blip every ``period_ms``. This is the README's canonical
    400 ms click track (librosa reads it as 400.1 ms beats, dead accurate)."""
    click = Sine(1000).to_audio_segment(duration=5).apply_gain(-1)
    rest = AudioSegment.silent(duration=period_ms - 5)
    track = AudioSegment.silent(duration=0)
    for _ in range(n_clicks):
        track += click + rest
    return track


def grain_starts(mix, silence_thresh=-40, min_silence_len=40):
    """Read grain-start timestamps back out of the rendered mix — the artifact, not an assertion."""
    regions = detect_nonsilent(mix, min_silence_len=min_silence_len,
                               silence_thresh=silence_thresh, seek_step=1)
    return [start for start, _end in regions]


def near(x, xs, tol):
    return any(abs(x - y) <= tol for y in xs)


# ---- 1. Grains land on the subdivision grid -------------------------------------------------
# 400 ms beat, E(3,8) -> 8 slots of 50 ms; hit slots {0,3,6} per beat -> output ms 0,150,300, then
# every bar: 400,550,700, ...  Assert each rendered grain start is within a few ms of a grid slot.
track = click_track(400, 5)  # 2000 ms
beats = [0, 400, 800, 1200, 1600]
cfg = AutoMixerConfig(track, beats, sample_length=100, mode="q", euclid_k=3, euclid_n=8)
mix = QuantizedAutoMixer().mix(cfg)

if len(mix) == 0:
    failures.append("quantized mix is empty on the click track")
else:
    slot_ms = 400 / 8  # 50
    hit_slots = [i for i in range(len(track) // int(slot_ms)) if euclidean(3, 8)[i % 8]]
    grid_ms = [i * slot_ms for i in hit_slots]
    starts = grain_starts(mix)
    if not starts:
        failures.append("no grains detected in the rendered click-track mix")
    else:
        off_grid = [s for s in starts if not near(s, grid_ms, 20)]
        if off_grid:
            failures.append("grain starts %r are off the 50 ms grid (expected near %r)"
                            % (off_grid, grid_ms))
        # Coverage: most grid hits produced a grain (allow the trailing slot to fall off the end).
        covered = [g for g in grid_ms if near(g, starts, 20)]
        if len(covered) < len(grid_ms) - 1:
            failures.append("only %d/%d grid hits produced a grain: starts=%r"
                            % (len(covered), len(grid_ms), starts))

# ---- 2. The euclidean pattern is AUDIBLE: E(3,8) tresillo gaps are 150,150,100 ms repeating ----
        starts_sorted = sorted(starts)
        gaps = [round(starts_sorted[i + 1] - starts_sorted[i]) for i in range(len(starts_sorted) - 1)]
        # tolerate +-15 ms detector jitter; the signature is the 3-in-8 shape {150,150,100}
        def close(a, b):
            return abs(a - b) <= 15
        good = sum(1 for i, g in enumerate(gaps) if close(g, [150, 150, 100][i % 3]))
        if gaps and good < len(gaps) - 1:
            failures.append("tresillo gap signature not visible: gaps=%r (expected 150,150,100 repeating)"
                            % gaps)

# ---- 3. Onset-aware boundaries: the mixer cuts at the source's transients, snapped to the grid --
onsets = QuantizedAutoMixer()._onsets(track, 50.0)
click_positions = [0, 400, 800, 1200, 1600]
matched = [c for c in click_positions if near(c, onsets, 30)]
if len(matched) < 4:
    failures.append("onset detection found the clicks at %r; expected ~%r (matched %d/5)"
                    % (onsets, click_positions, len(matched)))

# ---- 4. Beatless input still produces a non-empty mix (no beat floor) --------------------------
hum = WhiteNoise().to_audio_segment(duration=1500).apply_gain(-25)
cfg_hum = AutoMixerConfig(hum, [], sample_length=120, mode="q", euclid_k=3, euclid_n=8)
mix_hum = QuantizedAutoMixer().mix(cfg_hum)
if len(mix_hum) == 0 or mix_hum.dBFS == float("-inf"):
    failures.append("beatless input produced an empty/silent mix — a beat floor crept in")

# ---- 5. Grid placement is deterministic; grain CONTENT varies between runs ----------------------
cfg2 = AutoMixerConfig(track, beats, sample_length=100, mode="q", euclid_k=3, euclid_n=8)
mix_a = QuantizedAutoMixer().mix(cfg2)
mix_b = QuantizedAutoMixer().mix(cfg2)
starts_a, starts_b = grain_starts(mix_a), grain_starts(mix_b)
if starts_a != starts_b:
    failures.append("grid placement is NOT deterministic: %r vs %r" % (starts_a, starts_b))
if mix_a.raw_data == mix_b.raw_data:
    failures.append("two runs produced byte-identical audio — grain content is not varying")

# ---- 6. Gap-fill (operator 2026-07-18): rest slots are filled with off-grid remnants, not silence -
# On CONTINUOUS material (a tone bed the clicks ride on) the off-grid remnants are audible, so the
# euclidean REST slots must render sound with fill on and stay silent with fill off — and the HITS
# must still read as accents above the fills. On the pure click track the between-click remnants are
# silence, so gates 1-2 above (fill defaults on) are unaffected; this gate needs a non-silent bed.
def slot_dbfs(mix, i, slot_ms):
    seg = mix[int(i * slot_ms):int((i + 1) * slot_ms)]
    return seg.dBFS if len(seg) else float("-inf")

bed = Sine(200).to_audio_segment(duration=2000).apply_gain(-20)
clicks = click_track(400, 5)                      # 2000 ms, clicks at 0,400,800,1200,1600
src6 = bed.overlay(clicks)                         # continuous bed + transient onsets
beats6 = [0, 400, 800, 1200, 1600]
slot6 = 400 / 8                                    # 50 ms
pat6 = euclidean(3, 8)                             # [1,0,0,1,0,0,1,0]
nslots6 = len(src6) // int(slot6)
rest_idx = [i for i in range(nslots6) if not pat6[i % 8]]
hit_idx6 = [i for i in range(nslots6) if pat6[i % 8]]

cfg_fill = AutoMixerConfig(src6, beats6, sample_length=100, mode="q", euclid_k=3, euclid_n=8, fill=True)
cfg_nofill = AutoMixerConfig(src6, beats6, sample_length=100, mode="q", euclid_k=3, euclid_n=8, fill=False)
mix_fill = QuantizedAutoMixer().mix(cfg_fill)
mix_nofill = QuantizedAutoMixer().mix(cfg_nofill)

# (a) rest slots are SILENT without fill, and AUDIBLE with fill.
rest_sample = [i for i in rest_idx if i < nslots6 - 1][:12]
nofill_rest_loud = [i for i in rest_sample if slot_dbfs(mix_nofill, i, slot6) > -45]
fill_rest_loud = [i for i in rest_sample if slot_dbfs(mix_fill, i, slot6) > -45]
if nofill_rest_loud:
    failures.append("nofill: rest slots %r are not silent — a fill crept into the pure-grid path"
                    % nofill_rest_loud)
if len(fill_rest_loud) < max(1, len(rest_sample) // 2):
    failures.append("fill: only %d/%d rest slots got audible remnant fill (gaps still silent/choppy)"
                    % (len(fill_rest_loud), len(rest_sample)))

# (b) the fill adds sound overall (more non-silent audio than the silent-rest render).
ns_fill = sum(e - s for s, e in detect_nonsilent(mix_fill, min_silence_len=20, silence_thresh=-45))
ns_nofill = sum(e - s for s, e in detect_nonsilent(mix_nofill, min_silence_len=20, silence_thresh=-45))
if not ns_fill > ns_nofill:
    failures.append("fill did not add audible material: non-silent fill=%dms <= nofill=%dms"
                    % (ns_fill, ns_nofill))

# (c) HITS stay accented above the fills — the euclidean groove is still audible as amplitude.
hit_lvl = [slot_dbfs(mix_fill, i, slot6) for i in hit_idx6 if slot_dbfs(mix_fill, i, slot6) > float("-inf")]
fill_lvl = [slot_dbfs(mix_fill, i, slot6) for i in rest_idx if slot_dbfs(mix_fill, i, slot6) > float("-inf")]
if hit_lvl and fill_lvl:
    mean_hit = sum(hit_lvl) / len(hit_lvl)
    mean_fill = sum(fill_lvl) / len(fill_lvl)
    if not mean_hit > mean_fill + 1.5:
        failures.append("groove lost: mean hit %.1f dBFS not accented above mean fill %.1f dBFS"
                        % (mean_hit, mean_fill))

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("ok: grains land on the euclidean beat-subdivision grid; tresillo audible; "
      "beatless produces output; grid deterministic, content varies; "
      "rest slots filled with off-grid remnants (silent under nofill), hits stay accented")


# ---- Grain shaping wiring (2026-07-21): env_pct/reverse_prob reach _create_grain -----------------
import unittest
from unittest.mock import patch


class QuantizedMixerGrainShapeTest(unittest.TestCase):
    def test_env_zero_never_calls_fade(self):
        src = click_track(400, 5)
        beats = [0, 400, 800, 1200, 1600]
        cfg = AutoMixerConfig(src, beats, sample_length=100, mode="q", euclid_k=3, euclid_n=8,
                               env_pct=0.0)
        with patch("automixer.mixers.quantized_mixer.apply_envelope",
                   side_effect=lambda seg, pct: seg) as spy:
            QuantizedAutoMixer().mix(cfg)
        self.assertTrue(spy.called)
        for call in spy.call_args_list:
            self.assertEqual(call.args[1], 0.0)

    def test_reverse_prob_one_reverses_every_grain(self):
        src = click_track(400, 5)
        beats = [0, 400, 800, 1200, 1600]
        cfg = AutoMixerConfig(src, beats, sample_length=100, mode="q", euclid_k=3, euclid_n=8,
                               reverse_prob=1.0, seed=1)
        with patch("automixer.mixers.quantized_mixer.maybe_reverse",
                   wraps=lambda seg, prob, rng: seg.reverse() if prob >= 1.0 else seg) as spy:
            QuantizedAutoMixer().mix(cfg)
        self.assertTrue(spy.called)
        for call in spy.call_args_list:
            self.assertEqual(call.args[1], 1.0)


class QuantizedMixerReverseCoherenceTest(unittest.TestCase):
    """Regression for the "reverse decided independently per channel/band" bug: a multi-band
    ``channels_config`` (e.g. ``c 80,2000;2000,12000``) with ``0 < reverse_prob < 1`` must reverse
    or not reverse the WHOLE grain -- never one band forward and another reversed. Before the fix,
    ``maybe_reverse`` was called once per channel inside the loop; a 2-channel config would draw
    the reverse decision twice for what is meant to be a single coherent grain."""

    def test_reverse_decision_drawn_once_per_grain_not_per_channel(self):
        src = click_track(400, 5)
        channels = [ChannelConfig(80, 2000), ChannelConfig(2000, 12000)]
        cfg = AutoMixerConfig(src, [0, 400], sample_length=100, mode="q", euclid_k=3, euclid_n=8,
                               reverse_prob=0.5, seed=7, channels_config=channels)
        calls = []

        def spy(seg, prob, rng):
            # Deterministic alternation regardless of prob/rng: if the bug were present (one
            # call per channel), the two channels in this single grain would visibly disagree
            # (first call reversed, second forward). The real assertion is the call COUNT.
            calls.append(1)
            return seg.reverse() if len(calls) % 2 == 1 else seg

        with patch("automixer.mixers.quantized_mixer.maybe_reverse", side_effect=spy):
            QuantizedAutoMixer()._create_grain(cfg, onsets=[0], grain_len=100, candidates=[0])

        self.assertEqual(
            len(calls), 1,
            "reverse must be decided ONCE per grain and shared by every channel/band; got %d "
            "calls for a %d-channel config (a per-channel draw would scramble bands: one "
            "reversed, another forward, within the same grain)" % (len(calls), len(channels)))


if __name__ == "__main__":
    unittest.main()
