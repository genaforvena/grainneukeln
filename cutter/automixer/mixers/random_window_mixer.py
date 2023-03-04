import random
from tqdm import tqdm

class RandomWindowAutoMixer:
    def __init__(self, audio, beats, sample_length, is_verbose_mode_enabled):
        self.audio = audio
        self.beats = beats
        self.sample_length = sample_length
        self.is_verbose_mode_enabled = is_verbose_mode_enabled

    def mix(self, mix):
        start_cut = 0
        pbar = tqdm(total=len(self.audio))
        # determine the size of the 1/5th selection window
        window_size = len(self.beats) // 5
        while start_cut + self.sample_length < len(self.audio):
            # randomly select a start point within the 1/6th selection window
            start_window = random.randint(0, len(self.beats) - window_size)
            start = self.beats[start_window + random.randint(0, window_size - 1)]
            if start + self.sample_length > len(self.audio):
                continue
            if self.is_verbose_mode_enabled:
                print("Cutting from " + str(start) + " to " + str(start + self.sample_length))
            mix = mix.append(self.audio[start: start + self.sample_length], crossfade=0)
            if self.is_verbose_mode_enabled:
                print("Current mix length: " + str(len(mix)))
            start_cut += self.sample_length
            pbar.update(start_cut)
        pbar.close()
        return mix
