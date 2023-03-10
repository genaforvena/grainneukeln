from cutter.automixer.mixers.default_mixer import RandomWindowAutoMixer


class ChannelConfig:
    def __init__(self, low, high):
        if high == 0:
            high = 1
        if low == 0:
            low = 1
        self.high_pass = high
        self.low_pass = low

    def __str__(self):
        return "Low: " + str(self.low_pass) + "; High: " + str(self.high_pass)


class AutoMixerConfig:
    modes = {
        "rw": RandomWindowAutoMixer,
    }

    def __init__(self,
                 audio,
                 beats,
                 sample_length,
                 sample_speed=1.0,
                 mode="rw",
                 speed=1.0,
                 is_verbose_mode_enabled=False,
                 window_divider=2,
                 channels_config=[ChannelConfig(0, 15000)]):
        if mode not in self.modes:
            print("Invalid mode. Defaulting to random.")
            print("Valid modes: " + str(self.modes.keys()))
            mode = "rw"
        self.mode = mode
        self.audio = audio
        self.beats = beats
        self.sample_speed = sample_speed
        self.mixer = self.modes[mode]
        self.speed = speed
        self.sample_length = sample_length
        self.is_verbose_mode_enabled = is_verbose_mode_enabled
        self.window_divider = window_divider
        self.channels_config = channels_config

    def __str__(self):
        channel_config = [str(channel) for channel in self.channels_config]
        return "Audio: " + str(len(self.audio)) + "\n" + \
            "Beats: " + str(len(self.beats)) + "\n" + \
            "Mixer: " + str(self.mixer) + "\n" + \
            "Mode: " + str(self.mode) + "\n" + \
            "Speed: " + str(self.speed) + "\n" + \
            "Sample Length: " + str(self.sample_length) + "\n" + \
            "Sample Speed: " + str(self.sample_speed) + "\n" + \
            "Verbose Mode Enabled: " + str(self.is_verbose_mode_enabled) + "\n" + \
            "Window Divider: " + str(self.window_divider) + "\n" + \
            "Channels Config: " + str(channel_config) + "\n"
