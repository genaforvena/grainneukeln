from cutter.automixer.effects.change_tempo import ChangeTempo
from cutter.automixer.config import AutoMixerConfig


class AutoMixerRunner:
    def __init__(self, config: AutoMixerConfig):
        self.config = config
        self.mixer = config.mixer(audio=config.audio,
                                  beats=config.beats,
                                  sample_length=config.sample_length,
                                  is_verbose_mode_enabled=config.is_verbose_mode_enabled)

    def run(self, mix):
        mix = self.mixer.mix(mix)
        if self.config.speed == 1.0:
            mix = ChangeTempo().change_audioseg_tempo(mix, self.config.speed)
        return mix
