import random
from pydub import AudioSegment
from tqdm import tqdm

from cutter.automixer.channels_config import ChannelsConfig
from cutter.automixer.effects.band_pass import band_pass_filer
from cutter.automixer.mixers.iterators.rolling_window import rolling_window


class RandomWindowAutoMixer:
    def __init__(self, audio, beats,
                 sample_length: int,
                 is_verbose_mode_enabled: bool,
                 window_divider: int,
                 channels_config: ChannelsConfig):
        self.audio = audio
        self.beats = beats
        self.sample_length = sample_length
        self.window_divider = window_divider
        self.is_verbose_mode_enabled = is_verbose_mode_enabled
        self.channels_config = channels_config

    def mix(self, mix):
        pbar = tqdm(desc="Mixing")
        for window in rolling_window(self.beats, self.window_divider):
            chunk = AudioSegment.silent(duration=self.sample_length)
            # print("Current window length: " + str(len(window)))
            for channel in self.channels_config.channels:
                start_cut = random.choice(window)
                channel_chunk = self.audio[start_cut: start_cut + self.sample_length]
                channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
                # print("Current channel chunk length: " + str(len(channel_chunk)))
                chunk = chunk.overlay(channel_chunk)
                # print("Current chunk length: " + str(len(chunk)))
            mix = mix.append(chunk, crossfade=0)
            # print("Current mix length: " + str(len(mix)))
            pbar.update(len(mix))
        return mix
