from cutter.automixer.channels_config import ChannelConfig, ChannelsConfig
from cutter.automixer.mixers.old.random_mixer import RandomAutoMixer
from cutter.automixer.mixers.old.random_window_mixer import RandomWindowAutoMixer
from cutter.automixer.mixers.old.three_chan_mixer import ThreeChannelAutoMixer
from cutter.automixer.mixers.old.three_chan_window_mixer import ThreeChannelWindowAutoMixer
from cutter.automixer.mixers.default_mixer import DefaultRandomAutoMixer


class AutoMixerConfig:
    modes = {
        "r": RandomAutoMixer,
        "w": RandomWindowAutoMixer,
        "3": ThreeChannelAutoMixer,
        "3w": ThreeChannelWindowAutoMixer,
        "d": DefaultRandomAutoMixer,
    }

    def __init__(self, audio, beats, sample_length, mode="d", speed=1.0, is_verbose_mode_enabled=False,
                 window_divider=2, channels_config=ChannelsConfig([ChannelConfig(0, 15000)])):
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
        self.window_divider = window_divider
        self.channel_config = channels_config

    def __str__(self):
        return "Audio: " + str(len(self.audio)) + "\n" + \
               "Beats: " + str(len(self.beats)) + "\n" + \
               "Mixer: " + str(self.mixer) + "\n" + \
               "Mode: " + str(self.mode) + "\n" + \
               "Speed: " + str(self.speed) + "\n" + \
               "Sample Length: " + str(self.sample_length) + "\n" + \
               "Verbose Mode Enabled: " + str(self.is_verbose_mode_enabled) + "\n" + \
                "Window Divider: " + str(self.window_divider) + "\n" + \
                "Channels Config: " + str(self.channel_config) + "\n"
