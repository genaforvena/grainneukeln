"""library mixer (issue #7): feature-clustered grains + Markov-sequenced selection.

Zero-dep on purpose — this repo has no test runner. Run it directly:

    PYTHONPATH=. .venv/bin/python tests/test_library_mixer.py

Verification principle: the artifact, not the assertion. The mixer hands back the actual grain
SEQUENCE it played; the mean grain-to-grain distance in calibrated feature space is measured from that
sequence. The two policies must be measurably different — `similarity` keeps consecutive grains close,
`contrast` pushes them apart — not merely "both modes run". And too few grains to cluster must degrade
HONESTLY (a reported flag), never a faked full clustering.

O(n^2) note: sources kept short (<7 s).
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from pydub import AudioSegment
from pydub.generators import Sine, WhiteNoise

from automixer.config import AutoMixerConfig, ChannelConfig
from automixer.mixers.library_mixer import LibraryAutoMixer
from automixer.utils import slice_source

failures = []


def varied_source(reps=5):
    """A source that cycles through four distinct grain characters (bright / dark / noisy / dense)
    so the feature space genuinely clusters — the precondition for a sequencing policy to matter."""
    bright = Sine(6000).to_audio_segment(duration=400).apply_gain(-3)
    dark = Sine(150).to_audio_segment(duration=400).apply_gain(-3)
    noisy = WhiteNoise().to_audio_segment(duration=400).apply_gain(-10)
    click = Sine(1400).to_audio_segment(duration=8).apply_gain(-1)
    dense = AudioSegment.silent(duration=0)
    for _ in range(8):  # ~20 onsets/s
        dense += click + AudioSegment.silent(duration=42)
    dense = dense[:400]
    block = bright + dark + noisy + dense
    track = AudioSegment.silent(duration=0)
    for _ in range(reps):
        track += block
    beats = list(range(0, len(track), 400))
    return track, beats


def mean_transition_distance(debug):
    norm, seq = debug["norm"], debug["sequence"]
    if len(seq) < 2:
        return 0.0
    d = [np.linalg.norm(norm[seq[i + 1]] - norm[seq[i]]) for i in range(len(seq) - 1)]
    return float(np.mean(d))


track, beats = varied_source(5)  # 20 grains, 4 characters

# ---- 1. similarity vs contrast produce measurably different transition distances ---------------
# Average over several runs to average out the Markov RNG; the SEPARATION must be robust, not luck.
def policy_mean(policy, runs=6):
    vals = []
    for _ in range(runs):
        cfg = AutoMixerConfig(track, beats, sample_length=400, mode="lib",
                              lib_policy=policy, lib_clusters=4)
        _out, dbg = LibraryAutoMixer().mix(cfg, return_debug=True)
        if dbg.get("n_clusters", 0) < 2:
            failures.append("clustering collapsed to <2 clusters on a deliberately varied source")
            return None
        vals.append(mean_transition_distance(dbg))
    return float(np.mean(vals)), dbg["n_clusters"]

sim = policy_mean("similarity")
con = policy_mean("contrast")
if sim and con:
    sim_mean, ncl = sim
    con_mean, _ = con
    print("mean transition distance: similarity=%.3f  contrast=%.3f  (%d clusters)"
          % (sim_mean, con_mean, ncl))
    if not (con_mean > sim_mean):
        failures.append("contrast (%.3f) did not exceed similarity (%.3f) — policies not distinct"
                        % (con_mean, sim_mean))
    # measurably different, not a coin-flip: require a clear gap relative to the feature scale
    if con_mean - sim_mean < 0.15:
        failures.append("policy gap only %.3f — not a measurable difference" % (con_mean - sim_mean))

# ---- 2. Produces a real, non-empty mix on the varied (real-ish) source -------------------------
cfg = AutoMixerConfig(track, beats, sample_length=400, mode="lib", lib_policy="similarity", lib_clusters=4)
out = LibraryAutoMixer().mix(cfg)
if len(out) == 0 or out.dBFS == float("-inf"):
    failures.append("library mix is empty/silent on the varied source")

# ---- 3. Degrades HONESTLY on too few grains (reported, not faked) ------------------------------
short = track[:600]  # ~1 grain fits the beat grid
cfg_short = AutoMixerConfig(short, [0], sample_length=400, mode="lib", lib_clusters=6)
out_s, dbg_s = LibraryAutoMixer().mix(cfg_short, return_debug=True)
if not dbg_s.get("degraded"):
    failures.append("too-few-grains case did NOT set the honest-degrade flag (faked all-clear)")
if len(out_s) == 0:
    failures.append("degraded case produced no output at all")

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("ok: similarity keeps grains close, contrast pushes them apart (measurably different), "
      "and too-few-grains degrades honestly")


# ---- Grain shaping wiring (2026-07-21): env_pct/reverse_prob reach _render_grain -----------------
import unittest
from unittest.mock import patch


class LibraryMixerGrainShapeTest(unittest.TestCase):
    def test_env_zero_never_calls_fade(self):
        # varied_source(5) -> 20 beat-grid grains (>1) so apply_envelope is provably called more
        # than once, not just on a single degenerate grain.
        track5, beats5 = varied_source(5)
        cfg = AutoMixerConfig(track5, beats5, sample_length=400, mode="lib",
                               lib_policy="similarity", lib_clusters=4, env_pct=0.0)
        with patch("automixer.mixers.library_mixer.apply_envelope",
                   side_effect=lambda seg, pct: seg) as spy:
            LibraryAutoMixer().mix(cfg)
        self.assertGreater(spy.call_count, 1)
        for call in spy.call_args_list:
            self.assertEqual(call.args[1], 0.0)

    def test_reverse_prob_one_reverses_every_grain(self):
        track5, beats5 = varied_source(5)
        cfg = AutoMixerConfig(track5, beats5, sample_length=400, mode="lib",
                               lib_policy="similarity", lib_clusters=4, reverse_prob=1.0, seed=1)
        with patch("automixer.mixers.library_mixer.maybe_reverse",
                   wraps=lambda seg, prob, rng: seg.reverse() if prob >= 1.0 else seg) as spy:
            LibraryAutoMixer().mix(cfg)
        self.assertGreater(spy.call_count, 1)
        for call in spy.call_args_list:
            self.assertEqual(call.args[1], 1.0)


class LibraryMixerReverseCoherenceTest(unittest.TestCase):
    """Regression for the "reverse decided independently per channel/band" bug (see the twin
    tests in tests/test_quantized_mixer.py / tests/test_poly_mixer.py). ``_render_grain`` also
    used a FRESH ``random.Random()`` per channel (not just per grain) -- doubly independent --
    so a multi-band ``channels_config`` with ``0 < reverse_prob < 1`` could reverse one band and
    leave another forward within the same grain."""

    def test_reverse_decision_drawn_once_per_grain_not_per_channel(self):
        track5, beats5 = varied_source(2)
        channels = [ChannelConfig(80, 2000), ChannelConfig(2000, 12000)]
        cfg = AutoMixerConfig(track5, beats5, sample_length=400, mode="lib",
                               lib_policy="similarity", lib_clusters=4, reverse_prob=0.5,
                               seed=7, channels_config=channels)
        calls = []

        def spy(seg, prob, rng):
            calls.append(1)
            return seg.reverse() if len(calls) % 2 == 1 else seg

        grain = track5[:400]
        with patch("automixer.mixers.library_mixer.maybe_reverse", side_effect=spy):
            LibraryAutoMixer()._render_grain(cfg, grain, 0)

        self.assertEqual(
            len(calls), 1,
            "reverse must be decided ONCE per grain and shared by every channel/band; got %d "
            "calls for a %d-channel config (a per-channel draw -- including the old fresh "
            "random.Random() per channel -- would scramble bands within the same grain)"
            % (len(calls), len(channels)))


class LibraryMixerDualSourceTest(unittest.TestCase):
    def test_source2_channel_pulls_from_audio2(self):
        track5, beats5 = varied_source(5)
        secondary = WhiteNoise().to_audio_segment(duration=len(track5)).apply_gain(-10)
        cfg = AutoMixerConfig(
            track5, beats5, sample_length=400, mode="lib", lib_policy="similarity", lib_clusters=4,
            seed=7, channels_config=[ChannelConfig(0, 15000, bypass=True, source2=True)],
        )
        cfg.audio2 = secondary
        with patch("automixer.mixers.library_mixer.slice_source",
                   wraps=slice_source) as spy:
            LibraryAutoMixer().mix(cfg)
        self.assertTrue(spy.called)
        for call in spy.call_args_list:
            self.assertTrue(call.args[1].source2)


if __name__ == "__main__":
    unittest.main()
