import os
import unittest
from tui.state import SessionState, TrackSpec
from tui import engine

ASSET = os.path.join(os.path.dirname(__file__), "..", "assets", "test_audio.mp3")


def _load_cutter():
    from cutter.sample_cut_tool import SampleCutter
    return SampleCutter(os.path.abspath(ASSET), os.path.abspath("output"))


class BuildConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cutter = _load_cutter()   # loads + beat-detects once (slow-ish)

    def test_scalars_map(self):
        state = SessionState(cutter=self.cutter, speed=1.5, sample_speed=0.5,
                             window_divider=6, sample_length_ms=480)
        cfg = engine.build_config(self.cutter, state)
        self.assertEqual(cfg.speed, 1.5)
        self.assertEqual(cfg.sample_speed, 0.5)
        self.assertEqual(cfg.window_divider, 6)
        self.assertEqual(cfg.sample_length, 480)
        self.assertEqual(cfg.mode, "rw")

    def test_multitrack_maps_every_band(self):
        state = SessionState(cutter=self.cutter, sample_length_ms=480, tracks=[
            TrackSpec(1, 250), TrackSpec(251, 400), TrackSpec(10000, 15000)])
        cfg = engine.build_config(self.cutter, state)
        self.assertEqual(len(cfg.channels_config), 3)
        self.assertEqual(cfg.channels_config[0].low_pass, 1)
        self.assertEqual(cfg.channels_config[0].high_pass, 250)
        self.assertEqual(cfg.channels_config[2].low_pass, 10000)
        self.assertEqual(cfg.channels_config[2].high_pass, 15000)


class RunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cutter = _load_cutter()
        # The bundled asset is a full song; the mixer is ~O(n^2) in track length (see README).
        # Truncate audio AND beats to a short, coherent clip so this real render stays fast — it is
        # still a genuine end-to-end render, just of a few seconds.
        cls.cutter.audio = cls.cutter.audio[:4000]           # first 4 s
        cls.cutter.beats = cls.cutter.beats[cls.cutter.beats < 4000]

    def test_run_produces_audible_mp3(self):
        import tempfile
        from pydub import AudioSegment
        state = SessionState(cutter=self.cutter, sample_length_ms=300)
        cfg = engine.build_config(self.cutter, state)
        with tempfile.TemporaryDirectory() as d:
            calls = []
            path = engine.run(cfg, d, on_progress=lambda f: calls.append(f))
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 2000)     # non-empty mp3
            seg = AudioSegment.from_file(path)
            self.assertGreater(len(seg), 0)                     # has duration
            self.assertGreater(seg.dBFS, -40.0)                 # audible, not silent-fallback
            self.assertIn(1.0, calls)                           # progress reached completion
