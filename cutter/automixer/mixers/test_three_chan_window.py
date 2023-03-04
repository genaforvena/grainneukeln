import unittest
import pydub
from three_chan_window_mixer import ThreeChannelWindowAutoMixer


class TestThreeChannelWindowAutoMixer(unittest.TestCase):

    def setUp(self):
        self.audio = pydub.AudioSegment.silent(duration=5000)
        self.beats = [1000, 2000, 3000, 4000]
        self.sample_length = 1000
        self.mixer = ThreeChannelWindowAutoMixer(self.audio, self.beats, self.sample_length, False)

    def test_mix_output_length(self):
        mix = pydub.AudioSegment.empty()
        mix = self.mixer.mix(mix)
        self.assertEqual(5000, len(self.audio))

    def test_mix_output_channels(self):
        mix = pydub.AudioSegment.empty()
        mix = self.mixer.mix(mix)
        self.assertEqual(mix.channels, 1)

    def test_mix_output_frame_rate(self):
        mix = pydub.AudioSegment.empty()
        mix = self.mixer.mix(mix)
        self.assertEqual(mix.frame_rate, self.audio.frame_rate)

    def test_mix_output_sample_width(self):
        mix = pydub.AudioSegment.empty()
        mix = self.mixer.mix(mix)
        self.assertEqual(mix.sample_width, self.audio.sample_width)

    def test_mix_with_verbose_mode_enabled(self):
        self.mixer.is_verbose_mode_enabled = True
        mix = pydub.AudioSegment.empty()
        mix = self.mixer.mix(mix)
        self.assertEqual(5000, len(self.audio))


if __name__ == '__main__':
    unittest.main()

