import unittest
from tui.state import TrackSpec, SessionState


class TrackSpecTest(unittest.TestCase):
    def test_valid_range(self):
        self.assertTrue(TrackSpec(0, 15000).valid())
        self.assertTrue(TrackSpec(200, 400).valid())

    def test_invalid_range(self):
        self.assertFalse(TrackSpec(400, 200).valid())   # low >= high
        self.assertFalse(TrackSpec(-1, 100).valid())    # negative
        self.assertFalse(TrackSpec(100, 100).valid())   # equal


class SessionStateTest(unittest.TestCase):
    def test_defaults(self):
        s = SessionState()
        self.assertEqual(s.speed, 1.0)
        self.assertEqual(s.window_divider, 2)
        self.assertEqual(len(s.tracks), 1)
        self.assertEqual((s.tracks[0].low, s.tracks[0].high), (0, 15000))

    def test_not_runnable_without_cutter(self):
        ok, reason = SessionState(sample_length_ms=500).is_runnable()
        self.assertFalse(ok)
        self.assertIn("source", reason.lower())

    def test_not_runnable_without_length(self):
        ok, reason = SessionState(cutter=object(), sample_length_ms=0).is_runnable()
        self.assertFalse(ok)
        self.assertIn("length", reason.lower())

    def test_not_runnable_with_bad_track(self):
        ok, reason = SessionState(
            cutter=object(), sample_length_ms=500, tracks=[TrackSpec(400, 200)]
        ).is_runnable()
        self.assertFalse(ok)
        self.assertIn("track", reason.lower())

    def test_runnable(self):
        ok, reason = SessionState(cutter=object(), sample_length_ms=500).is_runnable()
        self.assertTrue(ok)
        self.assertEqual(reason, "")
