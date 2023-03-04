from tqdm import tqdm
import pydub
import pydub.effects
import random


class ThreeChannelWindowAutoMixer:
    def __init__(self, audio, beats, sample_length, is_verbose_mode_enabled):
        self.audio = audio
        self.beats = beats
        self.sample_length = sample_length
        self.is_verbose_mode_enabled = is_verbose_mode_enabled

    def mix(self, mix):
        start_cut = 0
        index = 0
        window_size = len(self.beats) / 6
        tries = 0
        pbar = tqdm(total=len(self.beats))
        while start_cut < len(self.audio):
            start = int(index)
            end = int(index * window_size)

            if start >= len(self.beats):
                print("Reached the end of track. Cut start: " + str(start) + " End: " + str(len(self.beats)))
                break

            if end >= len(self.beats):
                end = len(self.beats) - 1

            if start == end:
                start = 0
                end = len(self.beats) - 1

            start_low = random.choice(self.beats[start:end])
            start_mid = random.choice(self.beats[start:end])
            start_high = random.choice(self.beats[start:end])
            if tries > 100000:
                print("Tries exceeded")
                break
            if start_low + self.sample_length >= len(self.audio) or start_high + self.sample_length >= len(
                    self.audio) or start_mid + self.sample_length >= len(self.audio):
                print("Start or end out of range. Start: " + str(start) + " End: " + str(end))
                tries += 1
                continue
            if self.is_verbose_mode_enabled:
                print("Cutting low from " + str(start_low) + " to " + str(start_low + self.sample_length))
                print("Cutting mid from " + str(start_mid) + " to " + str(start_mid + self.sample_length))
                print("Cutting high from " + str(start_high) + " to " + str(start_high + self.sample_length))
            highs = pydub.effects.high_pass_filter(self.audio[start_high: start_high + self.sample_length], 300)
            lows_for_mids = pydub.effects.high_pass_filter(self.audio[start_mid: start_mid + self.sample_length], 300)
            mids = pydub.effects.low_pass_filter(lows_for_mids, 900)
            lows = pydub.effects.low_pass_filter(self.audio[start_low: start_low + self.sample_length], 300)

            mix = mix.append(highs.overlay(mids).overlay(lows), crossfade=0)
            if self.is_verbose_mode_enabled:
                print("Mix length: " + str(len(mix)))
            start_cut += self.sample_length
            pbar.update(index)
            index += 1
        print("Mix length: " + str(len(mix)))
        pbar.close()
        return mix
