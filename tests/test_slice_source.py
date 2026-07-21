import unittest

from pydub.generators import Sine

from automixer.config import AutoMixerConfig, ChannelConfig
from automixer.utils import slice_source


def _cfg(audio, audio2=None):
    cfg = AutoMixerConfig(audio=audio, beats=[], sample_length=200)
    cfg.audio2 = audio2
    return cfg


class SliceSourceTest(unittest.TestCase):
    def test_default_channel_slices_primary_source(self):
        primary = Sine(220).to_audio_segment(duration=2000)
        secondary = Sine(880).to_audio_segment(duration=2000)
        cfg = _cfg(primary, secondary)
        ch = ChannelConfig(0, 15000, bypass=True)
        out = slice_source(cfg, ch, 100, 200)
        self.assertEqual(bytes(out._data), bytes(primary[100:300]._data))

    def test_source2_channel_slices_secondary(self):
        primary = Sine(220).to_audio_segment(duration=2000)
        secondary = Sine(880).to_audio_segment(duration=2000)
        cfg = _cfg(primary, secondary)
        ch = ChannelConfig(0, 15000, bypass=True, source2=True)
        out = slice_source(cfg, ch, 100, 200)
        self.assertEqual(bytes(out._data), bytes(secondary[100:300]._data))

    def test_source2_channel_without_audio2_falls_back_to_primary(self):
        primary = Sine(220).to_audio_segment(duration=2000)
        cfg = _cfg(primary, audio2=None)
        ch = ChannelConfig(0, 15000, bypass=True, source2=True)
        out = slice_source(cfg, ch, 100, 200)
        self.assertEqual(bytes(out._data), bytes(primary[100:300]._data))

    def test_wraps_when_position_plus_length_exceeds_a_shorter_source2(self):
        primary = Sine(220).to_audio_segment(duration=5000)
        secondary = Sine(880).to_audio_segment(duration=300)  # much shorter than the beat grid
        cfg = _cfg(primary, secondary)
        ch = ChannelConfig(0, 15000, bypass=True, source2=True)
        out = slice_source(cfg, ch, 4800, 200)  # 4800 % 300 = 0 -> [0:200]; still full length
        self.assertEqual(len(out), 200)
        self.assertEqual(bytes(out._data), bytes(secondary[0:200]._data))

    def test_wraps_across_the_end_of_source2(self):
        primary = Sine(220).to_audio_segment(duration=5000)
        secondary = Sine(880).to_audio_segment(duration=300)
        cfg = _cfg(primary, secondary)
        ch = ChannelConfig(0, 15000, bypass=True, source2=True)
        out = slice_source(cfg, ch, 250, 100)  # [250:300] + [0:50] wrapped
        self.assertEqual(len(out), 100)
        expected = bytes(secondary[250:300]._data) + bytes(secondary[0:50]._data)
        self.assertEqual(bytes(out._data), expected)

    # -- Review finding 1: unconditional wraparound regressed ordinary single-source (primary
    # path) behaviour on the default/rw mixer. The wrap must be SOURCE-2-ONLY.

    def test_primary_source_near_tail_slice_truncates_no_wrap(self):
        primary = Sine(220).to_audio_segment(duration=1000)
        cfg = _cfg(primary, audio2=None)
        ch = ChannelConfig(0, 15000, bypass=True)  # default channel -> primary source
        out = slice_source(cfg, ch, 950, 200)
        # Legacy plain pydub slice: audio[950:1150] truncates to 50ms, never wraps the opening in.
        self.assertEqual(len(out), 50)
        self.assertEqual(bytes(out._data), bytes(primary[950:1150]._data))

    def test_source2_true_without_audio2_falls_back_and_truncates_near_tail(self):
        primary = Sine(220).to_audio_segment(duration=1000)
        cfg = _cfg(primary, audio2=None)
        ch = ChannelConfig(0, 15000, bypass=True, source2=True)
        out = slice_source(cfg, ch, 950, 200)
        self.assertEqual(len(out), 50)
        self.assertEqual(bytes(out._data), bytes(primary[950:1150]._data))


if __name__ == "__main__":
    unittest.main()
