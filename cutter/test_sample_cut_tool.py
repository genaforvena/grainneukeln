import unittest
from cutter.sample_cut_tool import SampleCutter


class TestSampleCutter(unittest.TestCase):

    def setUp(self):
        self.audio_file_path = "assets/test_audio.mp3"
        self.destination_path = "test_output"
        self.sample_cutter = SampleCutter(self.audio_file_path, self.destination_path)

    def test_load_audio(self):
        self.assertEqual(self.sample_cutter.audio_file_path, self.audio_file_path)
        self.assertEqual(self.sample_cutter.current_position, 0)
        self.assertIsNotNone(self.sample_cutter.beats)
        self.assertGreater(self.sample_cutter.step, 0)
        self.assertGreater(self.sample_cutter.sample_length, 0)

    def test_set_beginning(self):
        self.sample_cutter.set_beginning("b 1000")
        self.assertEqual(self.sample_cutter.current_position, 1000)

    def test_set_length(self):
        self.sample_cutter.set_length("l 2000")
        self.assertEqual(self.sample_cutter.sample_length, 2000)
        self.assertEqual(self.sample_cutter.auto_mixer_config.sample_length, 2000)

    def test_set_step(self):
        self.sample_cutter.set_step("s 500")
        self.assertEqual(self.sample_cutter.step, 500)

    def test_fast_forward(self):
        self.sample_cutter.current_position = 0
        self.sample_cutter.fast_forward("f")
        self.assertEqual(self.sample_cutter.current_position, self.sample_cutter.step)

    def test_rewind(self):
        self.sample_cutter.current_position = 5000
        self.sample_cutter.rewind("r")
        self.assertEqual(self.sample_cutter.current_position, 5000 - self.sample_cutter.step)

    def test_load_file(self):
        new_audio_file_path = "assets/test_audio_2.wav"
        self.sample_cutter.load_file("load " + new_audio_file_path)
        self.assertEqual(self.sample_cutter.audio_file_path, new_audio_file_path)

    def test_config_automix(self):
        sample_length_was = self.sample_cutter.auto_mixer_config.sample_length
        self.sample_cutter.config_automix("m 3w s 0.5 l /2")
        self.assertEqual(self.sample_cutter.auto_mixer_config.mode, "3w")
        self.assertEqual(self.sample_cutter.auto_mixer_config.speed, 0.5)
        self.assertEqual(self.sample_cutter.auto_mixer_config.sample_length, sample_length_was / 2)

    def test__adjust_cut_position(self):
        current_position = 5000
        length = 2000
        adjusted_position = self.sample_cutter._adjust_cut_position(current_position, length, threshold=0.05)
        self.assertEqual(adjusted_position, current_position)


if __name__ == '__main__':
    unittest.main()
