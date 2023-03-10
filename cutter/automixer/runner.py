from cutter.automixer.config import AutoMixerConfig
from cutter.automixer.effects.change_tempo import change_audioseg_tempo


class AutoMixerRunner:
    def run(self, config: AutoMixerConfig):
        mix = config.mixer().mix(config)
        if config.speed != 1.0:
            mix = change_audioseg_tempo(mix, config.speed)
        return mix
