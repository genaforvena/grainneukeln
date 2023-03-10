import random

from pydub import AudioSegment
from tqdm import tqdm

from cutter.automixer.effects.band_pass import band_pass_filer
from cutter.automixer.effects.change_tempo import change_audioseg_tempo
from cutter.automixer.iterators.rolling_window import rolling_window


class RandomWindowAutoMixer:
    def mix(self, config):
        mix = AudioSegment.empty()
        pbar = tqdm(desc="Mixing")
        for window in rolling_window(config.beats, config.window_divider):
            chunk = AudioSegment.silent(duration=config.sample_length)
            for channel in config.channels_config:
                start_cut = random.choice(window)
                channel_chunk = config.audio[start_cut: start_cut + config.sample_length]
                channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
                chunk = chunk.overlay(channel_chunk)
            if config.sample_speed != 1.0:
                chunk = change_audioseg_tempo(chunk, config.sample_speed)
            mix = mix.append(chunk, crossfade=0)
            pbar.update(len(mix))
        return mix