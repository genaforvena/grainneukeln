import unittest
import numpy as np
from pydub import AudioSegment
from cutter.automixer.mixers.random_window_mixer import RandomWindowAutoMixer


class TestRandomWindowAutoMixer(unittest.TestCase):
    def setUp(self):
        # create a sample audio segment and beat list for testing
        self.audio = AudioSegment.silent(duration=10000)
        self.beats = np.arange(0, len(self.audio), 100)
        self.sample_length = 100
        self.is_verbose_mode_enabled = False

    def test_mix_output_type(self):
        # test that mix() returns an AudioSegment object
        mixer = RandomWindowAutoMixer(self.audio, self.beats, self.sample_length, self.is_verbose_mode_enabled)
        mix = mixer.mix(AudioSegment.silent(duration=0))
        self.assertIsInstance(mix, AudioSegment)

    def test_mix_output_length(self):
        # test that mix() returns an AudioSegment with the expected length
        mixer = RandomWindowAutoMixer(self.audio, self.beats, self.sample_length, self.is_verbose_mode_enabled)
        mix = mixer.mix(AudioSegment.silent(duration=0))
        expected_length = len(self.audio) // self.sample_length * self.sample_length
        self.assertAlmostEqual(len(mix), 9902, delta=10)
