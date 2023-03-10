import random
from pydub import AudioSegment
from tqdm import tqdm

from cutter.automixer.channels_config import ChannelsConfig
from cutter.automixer.effects.band_pass import band_pass_filer
from cutter.automixer.mixers.iterators.rolling_window import RollingWindowIterator, rolling_window


class DefaultRandomAutoMixer:
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
        pbar = tqdm(total=len(self.audio))
        # slidging_window_iterator = RollingWindowIterator(self.audio, self.beats, self.window_divider,
        #                                                  self.sample_length)
        for window in rolling_window(self.beats, self.window_divider):
            chunk = AudioSegment.empty()
            print("Current window: " + str(window))
            for channel in self.channels_config.channels:
                start_cut = random.choice(window)
                if (start_cut + self.sample_length) > len(self.audio):
                    print("Not cutting out of range: " + str(start_cut) + " - " + str(start_cut + self.sample_length))
                    continue
                # chunk = mix.overlay(band_pass_filer(channel.low_pass, channel.high_pass,
                #                                     self.audio[start_cut: start_cut + self.sample_length]))
                chunk = self.audio[start_cut: start_cut + self.sample_length]
                print("Current chunk length: " + str(len(chunk)))
                if self.is_verbose_mode_enabled:
                    print("Current mix length: " + str(len(mix)))
            mix = mix.append(chunk, crossfade=0)
            print("Current mix length: " + str(len(mix)))
            pbar.update(len(mix))
        return mix
