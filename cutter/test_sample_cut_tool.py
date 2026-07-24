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
