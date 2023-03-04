from tqdm import tqdm
import random
import pydub


class ThreeChannelAutoMixer:
    def __init__(self, audio, beats, sample_length, is_verbose_mode_enabled):
        self.audio = audio
        self.beats = beats
        self.sample_length = sample_length
        self.is_verbose_mode_enabled = is_verbose_mode_enabled

    def _3chan_automix(self, mix):
        start_cut = 0
        index = 0
        tries = 0
        pbar = tqdm(total=len(self.beats))
        while start_cut + self.sample_length < len(self.audio) and index < len(self.beats):
            start_low = random.choice(self.beats)
            start_mid = random.choice(self.beats)
            start_high = random.choice(self.beats[index:])
            if tries > 100:
                return mix
            if start_low + self.sample_length == len(self.audio) or start_high + self.sample_length == len(self.audio) or start_mid + self.sample_length == len(self.audio):
                return mix
            if start_low + self.sample_length > len(self.audio) or start_high + self.sample_length > len(self.audio) or start_mid + self.sample_length > len(self.audio):
                tries += 1
                continue
            if self.is_verbose_mode_enabled:
                print("Cutting low from " + str(start_low) + " to " + str(start_low + self.sample_length))
                print("Cutting mid from " + str(start_mid) + " to " + str(start_mid + self.sample_length))
                print("Cutting high from " + str(start_high) + " to " + str(start_high + self.sample_length))
            mix = mix.append(
                pydub.effects.low_pass_filter(self.audio[start_low: start_low + self.sample_length], 300).overlay(
                    pydub.effects.high_pass_filter(self.audio[start_high: start_high + self.sample_length], 900)
                ).overlay(
                    pydub.effects.low_pass_filter(self.audio[start_mid: start_mid + self.sample_length], 900).overlay(
                        pydub.effects.high_pass_filter(self.audio[start_mid: start_mid + self.sample_length], 300)
                    )
                ), crossfade=0)
            if self.is_verbose_mode_enabled:
                print("Mix length: " + str(len(mix)))
            start_cut += self.sample_length
            pbar.update(index)
            index += 1
        pbar.close()
        return mix
