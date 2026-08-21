import unittest
import os

from cutter.sample_cut_tool import SampleCutter


class TestSampleCutter(unittest.TestCase):
    def setUp(self):
        # Anchor to this test file's directory so the suite passes from any cwd (matches the
        # os.path.dirname(__file__) idiom in cutter/test_series_cli.py); the bare "../assets/..."
        # path only resolved when pytest happened to run from cutter/.
        here = os.path.dirname(__file__)
        self.audio_file_path = os.path.join(here, "..", "assets", "test_audio.mp3")
        self.destination_path = os.path.join(here, "..", "test_samples")
        os.makedirs(self.destination_path, exist_ok=True)
        self.sample_cutter = SampleCutter(self.audio_file_path, self.destination_path)

    def tearDown(self):
        # Clean up any created sample files
        for file in os.listdir(self.destination_path):
            os.remove(os.path.join(self.destination_path, file))

    def test_load_audio(self):
        # Test that an exception is raised if the file does not exist
        with self.assertRaises(Exception):
            sample_cutter = SampleCutter("non_existent_file.wav", self.destination_path)

        # Test that the audio file is loaded correctly
        self.assertEqual(self.sample_cutter.audio_file_path, self.audio_file_path)
        self.assertIsNotNone(self.sample_cutter.audio)

    def test_detect_beats(self):
        # Test that beats are detected correctly
        beats = self.sample_cutter._detect_beats()
        self.assertIsNotNone(beats)
        self.assertGreater(len(beats), 0)

    def test_save_mix(self):
        # Test that a mix file is saved to the destination path
        mix = self.sample_cutter.audio[:self.sample_cutter.step] + self.sample_cutter.audio[self.sample_cutter.step:self.sample_cutter.step * 2].fade_out(500)
        self.sample_cutter._save_mix(mix)
        files = os.listdir(self.destination_path)
        self.assertTrue(files[0].endswith(".mp3"))

    def test_auto_mixer_config(self):
        # Test that the AutoMixer config is updated correctly
        args = "amc m rw s 0.5 ss 0.5 w 2 c 0,200;200,400 l 500"
        self.sample_cutter.config_automix(args)
        config = self.sample_cutter.auto_mixer_config
        self.assertEqual(config.mode, "rw")
        self.assertEqual(config.speed, 0.5)
        self.assertEqual(config.sample_speed, 0.5)
        self.assertEqual(config.window_divider, 2)
        self.assertEqual(len(config.channels_config), 2)
        self.assertEqual(config.channels_config[0].low_pass, 1)
        self.assertEqual(config.channels_config[0].high_pass, 200)
        self.assertEqual(config.channels_config[1].low_pass, 200)
        self.assertEqual(config.channels_config[1].high_pass, 400)

    def test_m_lib_mode_does_not_crash_on_lib_policy_token_collision(self):
        # `lib` is BOTH the library-mixer mode value (`m lib`) and the policy token (`lib sim|con`).
        # Pre-fix, `amc m lib` made config_automix read past the end of args (IndexError) because
        # the mode value had no policy word after it. This is a hot path under Uxn ROM control,
        # which emits `m lib` on every library-period tick. Assert it now sets mode=lib cleanly,
        # and that an explicit policy still parses when present alongside `m lib`.
        self.sample_cutter.config_automix("amc m lib")
        self.assertEqual(self.sample_cutter.auto_mixer_config.mode, "lib")

        self.sample_cutter.config_automix("amc m lib lib con")
        self.assertEqual(self.sample_cutter.auto_mixer_config.mode, "lib")
        self.assertEqual(self.sample_cutter.auto_mixer_config.lib_policy, "contrast")

if __name__ == "__main__":
    unittest.main()


class TestSaveMixFilename(unittest.TestCase):
    """A render is discarded at the LAST step if the filename it is given cannot exist.

    ``_save_mix`` encodes the config into the name. The poly-mixer ``streams`` field is a list of
    dicts holding ChannelConfig OBJECTS, and it was interpolated with a bare f-string — so a banded
    ``pr 7:60-500;3:500-2500`` produced a name carrying ``<automixer.config.ChannelConfig object at
    0x...>`` per stream, blowing NAME_MAX (255) and raising OSError 36 *after* the whole mix was
    computed. The name also leaked a heap address, so two byte-identical renders never shared a name.
    """

    def setUp(self):
        here = os.path.dirname(__file__)
        self.audio_file_path = os.path.join(here, "..", "assets", "test_audio.mp3")
        self.destination_path = os.path.join(here, "..", "test_samples")
        os.makedirs(self.destination_path, exist_ok=True)
        self.sample_cutter = SampleCutter(self.audio_file_path, self.destination_path)

    def tearDown(self):
        for file in os.listdir(self.destination_path):
            os.remove(os.path.join(self.destination_path, file))

    def _tiny_mix(self):
        return self.sample_cutter.audio[:200]

    def test_banded_poly_streams_produce_a_saveable_name(self):
        self.sample_cutter.config_automix(
            "amc m poly pr 7:60-500;3:500-2500;11:2500-12000 seed 802")
        self.sample_cutter._save_mix(self._tiny_mix())
        files = os.listdir(self.destination_path)
        self.assertEqual(len(files), 1, files)
        name = files[0]
        self.assertLessEqual(len(name.encode()), 255, f"NAME_MAX blown: {len(name)} bytes")
        self.assertNotIn("object at", name)
        self.assertNotIn("0x", name)
        # The spec is still legible in the name — it is what lets an operator ask for this render
        # again, which is the whole reason params are encoded there.
        self.assertIn("st7:60-500+3:500-2500+11:2500-12000", name)

    def test_bare_poly_ratios_produce_a_saveable_name(self):
        self.sample_cutter.config_automix("amc m poly pr 4;3 seed 5")
        self.sample_cutter._save_mix(self._tiny_mix())
        name = os.listdir(self.destination_path)[0]
        self.assertNotIn("object at", name)
        self.assertIn("st4+3", name)

    def test_a_name_longer_than_name_max_is_clamped_not_raised(self):
        # Many narrow bands is the other way to overflow: the ``c`` cutoff list is unbounded too.
        bands = ";".join(f"{i},{i + 10}" for i in range(100, 3000, 100))
        self.sample_cutter.config_automix("amc c " + bands)
        self.sample_cutter._save_mix(self._tiny_mix())
        name = os.listdir(self.destination_path)[0]
        self.assertLessEqual(len(name.encode()), 255, f"NAME_MAX blown: {len(name)} bytes")
        self.assertTrue(name.endswith(".mp3"), name)
