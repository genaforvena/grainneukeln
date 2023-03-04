from cutter.automixer.mixers.random_mixer import RandomAutoMixer
from cutter.automixer.mixers.random_window_mixer import RandomWindowAutoMixer
from cutter.automixer.mixers.three_chan_mixer import ThreeChannelAutoMixer
from cutter.automixer.mixers.three_chan_window_mixer import ThreeChannelWindowAutoMixer


class AutoMixerConfig:
    modes = {
        "r": RandomAutoMixer,
        "w": RandomWindowAutoMixer,
        "3": ThreeChannelAutoMixer,
        "3w": ThreeChannelWindowAutoMixer
    }

    def __init__(self, audio, beats, sample_length, mode="", speed=1.0, is_verbose_mode_enabled=False):
        if mode not in self.modes:
            print("Invalid mode. Defaulting to random.")
            print("Valid modes: " + str(self.modes.keys()))
            mode = "r"
        self.mode = mode
        self.audio = audio
        self.beats = beats
        self.mixer = self.modes[mode]
        self.speed = speed
        self.sample_length = sample_length
        self.is_verbose_mode_enabled = is_verbose_mode_enabled

    def __str__(self):
        return "Audio: " + str(len(self.audio)) + "\n" + \
               "Beats: " + str(len(self.beats)) + "\n" + \
               "Mixer: " + str(self.mixer) + "\n" + \
               "Mode: " + str(self.mode) + "\n" + \
               "Speed: " + str(self.speed) + "\n" + \
               "Sample Length: " + str(self.sample_length) + "\n" + \
               "Verbose Mode Enabled: " + str(self.is_verbose_mode_enabled)
