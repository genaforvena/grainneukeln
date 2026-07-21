import unittest
from unittest.mock import patch

import numpy as np
from pydub.generators import Sine

from automixer.config import AutoMixerConfig
from automixer.mixers.default_mixer import RandomWindowAutoMixer, _create_chunk


def _short_source(ms=4000):
    return Sine(220).to_audio_segment(duration=ms)


class DefaultMixerGrainShapeTest(unittest.TestCase):
    def test_env_zero_never_calls_fade(self):
        audio = _short_source()
        beats = np.array([0, 400, 800, 1200, 1600, 2000, 2400, 2800, 3200])
        cfg = AutoMixerConfig(audio=audio, beats=beats, sample_length=200, env_pct=0.0,
                               window_divider=2)
        with patch("automixer.mixers.default_mixer.apply_envelope",
                   side_effect=lambda seg, pct: seg) as spy:
            RandomWindowAutoMixer().mix(cfg)
        # called once per _create_chunk invocation, always with pct=0.0
        self.assertTrue(spy.called)
        for call in spy.call_args_list:
            self.assertEqual(call.args[1], 0.0)

    def test_reverse_prob_one_reverses_every_grain(self):
        audio = _short_source()
        beats = np.array([0, 400, 800, 1200, 1600, 2000, 2400, 2800, 3200])
        cfg = AutoMixerConfig(audio=audio, beats=beats, sample_length=200, reverse_prob=1.0,
                               window_divider=2, seed=1)
        with patch("automixer.mixers.default_mixer.maybe_reverse",
                   wraps=lambda seg, prob, rng: seg.reverse() if prob >= 1.0 else seg) as spy:
            RandomWindowAutoMixer().mix(cfg)
        self.assertTrue(spy.called)
        for call in spy.call_args_list:
            self.assertEqual(call.args[1], 1.0)


if __name__ == "__main__":
    unittest.main()
