import unittest

from automixer.features import AXES, measure_grain


class HpssAxisTest(unittest.TestCase):
    def test_axes_includes_hpss_ratio(self):
        self.assertIn("hpss_ratio", AXES)
        self.assertEqual(len(AXES), 4)

    def test_measure_grain_returns_hpss_ratio(self):
        from pydub.generators import Sine
        seg = Sine(440).to_audio_segment(duration=500)
        feats = measure_grain(seg)
        self.assertIn("hpss_ratio", feats)
        self.assertTrue(0.0 <= feats["hpss_ratio"] <= 1.0)

    def test_hpss_ratio_discriminates_tonal_vs_percussive(self):
        # A pure sustained sine is harmonic-dominant (low percussive ratio); white noise bursts
        # read as percussive-dominant (high ratio) -- the axis must not saturate/constant-out
        # (mesh doctrine: an axis whose real values pin at one end silently drops from clustering).
        from pydub.generators import Sine, WhiteNoise
        tonal = measure_grain(Sine(440).to_audio_segment(duration=800))
        percussive = measure_grain(WhiteNoise().to_audio_segment(duration=800))
        self.assertLess(tonal["hpss_ratio"], percussive["hpss_ratio"])


if __name__ == "__main__":
    unittest.main()
