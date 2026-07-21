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

    def test_mode_and_effects_map(self):
        state = SessionState(
            cutter=self.cutter, sample_length_ms=480,
            mode="q", euclid_k=5, euclid_n=13, snap=True, swing=66.0,
            fill=False, fill_gain_db=-3.0,
            lib_policy="contrast", lib_clusters=8,
            streams_spec="4:1-2000;3:6000-15000")
        cfg = engine.build_config(self.cutter, state)
        self.assertEqual(cfg.mode, "q")
        self.assertEqual((cfg.euclid_k, cfg.euclid_n), (5, 13))
        self.assertTrue(cfg.snap)
        self.assertEqual(cfg.swing, 66.0)
        self.assertFalse(cfg.fill)
        self.assertEqual(cfg.fill_gain_db, -3.0)
        self.assertEqual(cfg.lib_policy, "contrast")
        self.assertEqual(cfg.lib_clusters, 8)
        self.assertEqual(len(cfg.streams), 2)
        self.assertEqual(cfg.streams[0]["ratio"], 4)
        self.assertEqual(cfg.streams[0]["channels"][0].low_pass, 1)
        self.assertEqual(cfg.streams[0]["channels"][0].high_pass, 2000)
        self.assertEqual(cfg.streams[1]["ratio"], 3)

    def test_empty_streams_spec_is_none(self):
        state = SessionState(cutter=self.cutter, sample_length_ms=480, mode="poly")
        cfg = engine.build_config(self.cutter, state)
        self.assertIsNone(cfg.streams)   # mixer default (3-against-4), not a crash

    def test_multitrack_maps_every_band(self):
        state = SessionState(cutter=self.cutter, sample_length_ms=480, tracks=[
            TrackSpec(1, 250), TrackSpec(251, 400), TrackSpec(10000, 15000)])
        cfg = engine.build_config(self.cutter, state)
        self.assertEqual(len(cfg.channels_config), 3)
        self.assertEqual(cfg.channels_config[0].low_pass, 1)
        self.assertEqual(cfg.channels_config[0].high_pass, 250)
        self.assertEqual(cfg.channels_config[2].low_pass, 10000)
        self.assertEqual(cfg.channels_config[2].high_pass, 15000)

    def test_verbose_flows_into_build_config(self):
        # is_verbose_mode_enabled was hardcoded False in build_config; now it tracks state.verbose.
        state = SessionState(cutter=self.cutter, sample_length_ms=200, verbose=True)
        self.assertTrue(engine.build_config(self.cutter, state).is_verbose_mode_enabled)
        state.verbose = False
        self.assertFalse(engine.build_config(self.cutter, state).is_verbose_mode_enabled)

    def test_env_pct_and_reverse_prob_map(self):
        state = SessionState(cutter=self.cutter, sample_length_ms=480,
                             env_pct=15.0, reverse_prob=0.3)
        cfg = engine.build_config(self.cutter, state)
        self.assertEqual(cfg.env_pct, 15.0)
        self.assertEqual(cfg.reverse_prob, 0.3)

    def test_track_source2_maps_to_channel_config(self):
        state = SessionState(cutter=self.cutter, sample_length_ms=480,
                             tracks=[TrackSpec(0, 100, source2=True), TrackSpec(100, 200)])
        cfg = engine.build_config(self.cutter, state)
        self.assertTrue(cfg.channels_config[0].source2)
        self.assertFalse(cfg.channels_config[1].source2)


class _FakeCutter:
    """A minimal stand-in exposing exactly the surface build_config touches — no real audio I/O,
    so the test stays fast and does not depend on a loadable second file existing on disk."""
    def __init__(self):
        self.audio = "fake-audio"
        self.beats = "fake-beats"
        self.low_memory = False
        self.audio2 = None
        self.load_calls = []

    def _load_secondary_audio(self, path):
        self.load_calls.append(path)
        self.audio2 = f"audio2:{path}"


class BuildConfigSource2LoadTest(unittest.TestCase):
    """Dual-source grinding (2026-07-21): build_config triggers the secondary-source load itself,
    since every run path (single/series/uxn) already calls it."""

    def test_source2_path_triggers_secondary_load(self):
        cutter = _FakeCutter()
        state = SessionState(cutter=cutter, sample_length_ms=480, source2_path="/tmp/second.wav")
        cfg = engine.build_config(cutter, state)
        self.assertEqual(cutter.load_calls, ["/tmp/second.wav"])
        self.assertEqual(cfg.audio2, "audio2:/tmp/second.wav")

    def test_blank_source2_path_does_not_load(self):
        cutter = _FakeCutter()
        state = SessionState(cutter=cutter, sample_length_ms=480, source2_path="")
        cfg = engine.build_config(cutter, state)
        self.assertEqual(cutter.load_calls, [])
        self.assertIsNone(cfg.audio2)


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
            # default: no wav
            self.assertFalse(any(p.endswith(".wav") for p in os.listdir(d)))

    def test_run_writes_wav_alongside_mp3_when_requested(self):
        import tempfile
        from pydub import AudioSegment
        state = SessionState(cutter=self.cutter, sample_length_ms=300)
        cfg = engine.build_config(self.cutter, state)
        with tempfile.TemporaryDirectory() as d:
            mp3_path = engine.run(cfg, d, wav_export=True)
            files = sorted(os.listdir(d))
            self.assertTrue(any(f.endswith(".mp3") for f in files))   # mp3 always
            self.assertTrue(any(f.endswith(".wav") for f in files))   # wav when requested
            # Same base name — wav sits next to mp3, not as a separate render.
            base = os.path.splitext(os.path.basename(mp3_path))[0]
            self.assertIn(base + ".wav", files)
            wav_seg = AudioSegment.from_file(os.path.join(d, base + ".wav"))
            self.assertGreater(len(wav_seg), 0)


class OutputOptionsTest(unittest.TestCase):
    """The three CLI cutter toggles the TUI was missing (WAV / verbose / self-feed) all map onto
    SessionState as plain boolean defaults-off — locks in the parity the run-panel checkboxes expose."""
    def test_defaults_are_off(self):
        s = SessionState()
        self.assertFalse(s.wav_export)
        self.assertFalse(s.verbose)
        self.assertFalse(s.self_feed)
