"""End-to-end tests for series runs through the CLI ``SampleCutter`` path.

The series grammar itself is unit-tested in automixer/test_series.py; these tests verify the
wiring into ``SampleCutter.handle_input`` and ``config_automix`` — that the cartesian product
actually iterates and produces one exported file per combination, and that each render's params
land in the saved filename (so the operator can tell them apart).
"""
import os
import tempfile
import unittest

from cutter.sample_cut_tool import SampleCutter

ASSET = os.path.join(os.path.dirname(__file__), "..", "assets", "test_audio.mp3")


class SeriesCLITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cutter = SampleCutter(os.path.abspath(ASSET), os.path.abspath("output"))
        # The bundled asset is a full song; truncate audio + beats to a short coherent clip so the
        # renders stay fast (mirrors tui/test_engine.py). Still a genuine end-to-end render.
        cls.cutter.audio = cls.cutter.audio[:4000]
        cls.cutter.beats = cls.cutter.beats[cls.cutter.beats < 4000]

    def _count_renders(self, args):
        """Run a series via handle_input in a temp dir, return the list of exported filenames."""
        with tempfile.TemporaryDirectory() as d:
            cutter = SampleCutter(os.path.abspath(ASSET), d)
            cutter.audio = self.cutter.audio
            cutter.beats = self.cutter.beats
            cutter.sample_length = 300
            cutter.handle_input(args)
            files = sorted(os.listdir(d))
        return files

    def test_single_param_list_renders_n_files(self):
        files = self._count_renders(["amc", "l", "300", "w", "[2,4]"])
        self.assertEqual(len(files), 2)
        # Each filename encodes its own w value (w2 / w4) so the operator can tell them apart.
        self.assertTrue(any("w2" in f for f in files))
        self.assertTrue(any("w4" in f for f in files))

    def test_cartesian_two_params(self):
        files = self._count_renders(["amc", "w", "[2,4]", "s", "[0.9,1.1]"])
        self.assertEqual(len(files), 4)
        # All four w×s combinations present, each labelled with its own values.
        combos = {("w2" in f, "s0.9" in f) for f in files}
        combos_full = {
            (any(c in f for c in ("w2",)), any(s in f for s in ("s0.9", "s1.1")))
            for f in files
        }
        # Easier: assert all four combinations are distinguishable by their params in the filename.
        names = " ".join(files)
        for w in ("w2", "w4"):
            for s in ("s0.9", "s1.1"):
                # The CLI's _save_mix emits one filename per render with these params encoded; the
                # presence of both w and s in the same file is what distinguishes each combination.
                self.assertTrue(any(w in f and s in f for f in files),
                                f"missing render with {w} and {s} in {files}")

    def test_range_renders_n_files(self):
        files = self._count_renders(["amc", "l", "[100:200:50]"])
        self.assertEqual(len(files), 3)  # 100, 150, 200

    def test_no_series_is_single_render(self):
        # Without brackets, handle_input is the legacy single-shot path — one render, one file.
        files = self._count_renders(["amc", "l", "300", "w", "4"])
        self.assertEqual(len(files), 1)

    def test_interactive_amc_arms_series_then_am_runs_all(self):
        # Interactive path: ``amc l [/2,/3,/4]`` arms ``_pending_series`` and configures with the
        # first combination; ``am`` then iterates every combination. ``am N`` runs only #N.
        with tempfile.TemporaryDirectory() as d:
            cutter = SampleCutter(os.path.abspath(ASSET), d)
            cutter.audio = self.cutter.audio
            cutter.beats = self.cutter.beats
            cutter.sample_length = 400
            cutter.config_automix("amc l [/2,/3,/4]")
            self.assertEqual(len(cutter._pending_series), 3)
            cutter.automix("am")
            self.assertEqual(len(os.listdir(d)), 3)

    def test_interactive_am_n_runs_single(self):
        with tempfile.TemporaryDirectory() as d:
            cutter = SampleCutter(os.path.abspath(ASSET), d)
            cutter.audio = self.cutter.audio
            cutter.beats = self.cutter.beats
            cutter.sample_length = 400
            cutter.config_automix("amc s [0.9,1.0,1.1]")
            cutter.automix("am 2")  # only the 2nd combination
            self.assertEqual(len(os.listdir(d)), 1)

    def test_interactive_am_n_out_of_range_warns(self):
        with tempfile.TemporaryDirectory() as d:
            cutter = SampleCutter(os.path.abspath(ASSET), d)
            cutter.audio = self.cutter.audio
            cutter.beats = self.cutter.beats
            cutter.sample_length = 400
            cutter.config_automix("amc s [0.9,1.1]")
            cutter.automix("am 99")  # out of range — emits a message, renders nothing
            self.assertEqual(len(os.listdir(d)), 0)

    def test_plain_amc_clears_pending(self):
        # After a series, a plain non-series ``amc`` should reset to single-render behaviour.
        with tempfile.TemporaryDirectory() as d:
            cutter = SampleCutter(os.path.abspath(ASSET), d)
            cutter.audio = self.cutter.audio
            cutter.beats = self.cutter.beats
            cutter.sample_length = 400
            cutter.config_automix("amc s [0.9,1.1]")
            self.assertIsNotNone(cutter._pending_series)
            cutter.config_automix("amc s 1.0")
            self.assertIsNone(cutter._pending_series)
            cutter.automix("am")
            self.assertEqual(len(os.listdir(d)), 1)


class EnvRvTokenParsingTest(unittest.TestCase):
    """Grain shaping (2026-07-21): `amc env <pct>` / `amc rv <0..1>` token parsing into
    AutoMixerConfig.env_pct / .reverse_prob. Uses the same os.path.abspath(ASSET) pattern as the
    rest of this file — cutter/test_sample_cut_tool.py's bare "../assets/..." path only resolves
    when cwd is cutter/, which is not true under `pytest` run from the repo root (4 pre-existing,
    unrelated failures there, commit 4906246)."""

    def setUp(self):
        self.cutter = SampleCutter(os.path.abspath(ASSET), os.path.abspath("output"))

    def test_env_token_sets_env_pct(self):
        self.cutter.config_automix("amc env 15")
        self.assertEqual(self.cutter.auto_mixer_config.env_pct, 15.0)

    def test_rv_token_sets_reverse_prob(self):
        self.cutter.config_automix("amc rv 0.3")
        self.assertEqual(self.cutter.auto_mixer_config.reverse_prob, 0.3)

    def test_defaults_when_absent(self):
        self.cutter.config_automix("amc l 200")
        self.assertEqual(self.cutter.auto_mixer_config.env_pct, 8.0)
        self.assertEqual(self.cutter.auto_mixer_config.reverse_prob, 0.0)


class DualSourceCliTest(unittest.TestCase):
    """Dual-source grinding (2026-07-21): `amc src2 <path>` loads a second file into
    SampleCutter.audio2 (cached by path); a `c` band prefixed `2:` tags its ChannelConfig with
    source2=True. Same os.path.abspath(ASSET) pattern as the rest of this file (see
    EnvRvTokenParsingTest's docstring for why)."""

    def setUp(self):
        self.cutter = SampleCutter(os.path.abspath(ASSET), os.path.abspath("output"))

    def test_src2_loads_and_stores(self):
        self.cutter.config_automix("amc src2 " + ASSET)
        self.assertIsNotNone(self.cutter.audio2)
        self.assertEqual(self.cutter.auto_mixer_config.audio2, self.cutter.audio2)

    def test_c_grammar_2_prefix_tags_source2(self):
        self.cutter.config_automix("amc src2 " + ASSET + " c 0,250;2:1000,15000")
        channels = self.cutter.auto_mixer_config.channels_config
        self.assertEqual(len(channels), 2)
        self.assertFalse(channels[0].source2)
        self.assertTrue(channels[1].source2)
        self.assertEqual((channels[1].low_pass, channels[1].high_pass), (1000, 15000))

    def test_src2_is_cached_by_path(self):
        self.cutter.config_automix("amc src2 " + ASSET)
        first = self.cutter.audio2
        self.cutter.config_automix("amc src2 " + ASSET)
        self.assertIs(self.cutter.audio2, first)


if __name__ == "__main__":
    unittest.main()
