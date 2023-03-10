import unittest
import os

from cutter.sample_cut_tool import SampleCutter


class TestSampleCutter(unittest.TestCase):
    def setUp(self):
        self.audio_file_path = "../assets/test_audio.mp3"
        self.destination_path = "../test_samples"
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

if __name__ == "__main__":
    unittest.main()
