import unittest

from pydub.generators import Sine

from cutter.sample_cut_tool import normalize_loudness


class TestNormalizeLoudness(unittest.TestCase):
    TARGET = -16.0
    PEAK = -1.0

    def _tone(self, gain_db, ms=1000):
        # a 220Hz tone at (roughly) the requested peak level
        return Sine(220).to_audio_segment(duration=ms).apply_gain(gain_db)

    def test_quiet_tone_is_lifted_to_target(self):
        # a tone ~40 dB down (the near-inaudible regime the automix routinely lands in)
        seg = self._tone(-40)
        out = normalize_loudness(seg, self.TARGET, self.PEAK)
        # it must move substantially up toward the target, and stay peak-safe
        self.assertGreater(out.dBFS, seg.dBFS + 15)
        self.assertLessEqual(out.max_dBFS, self.PEAK + 0.5)
        # with ample headroom the RMS should reach the target closely
        self.assertAlmostEqual(out.dBFS, self.TARGET, delta=2.0)

    def test_hot_tone_is_pulled_down_to_be_peak_safe(self):
        # a tone already at full scale must be attenuated so the peak clears the ceiling
        seg = self._tone(0)
        out = normalize_loudness(seg, self.TARGET, self.PEAK)
        self.assertLessEqual(out.max_dBFS, self.PEAK + 0.5)
        self.assertLess(out.dBFS, seg.dBFS)

    def test_peak_ceiling_wins_over_target_for_transient_material(self):
        # a mostly-quiet tone with a single hot transient: the peak safety must bound the boost so the
        # export never clips, even though that leaves the RMS below target (documented tradeoff).
        quiet = self._tone(-40, ms=1000)
        transient = self._tone(0, ms=20)
        seg = quiet + transient
        out = normalize_loudness(seg, self.TARGET, self.PEAK)
        self.assertLessEqual(out.max_dBFS, self.PEAK + 0.5)

    def test_silence_is_returned_untouched(self):
        from pydub import AudioSegment

        seg = AudioSegment.silent(duration=500)
        out = normalize_loudness(seg, self.TARGET, self.PEAK)
        self.assertEqual(out.dBFS, seg.dBFS)


if __name__ == "__main__":
    unittest.main()
