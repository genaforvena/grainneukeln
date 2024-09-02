from automixer.config import AutoMixerConfig
from automixer.effects.change_tempo import change_audioseg_tempo


class AutoMixerRunner:
    def run(self, config: AutoMixerConfig):
        if config.beats is None:
            raise ValueError("Beats must be provided in the config")
        
        mix = config.mixer().mix(config)
        if config.speed != 1.0:
            mix = change_audioseg_tempo(mix, config.speed, verbose=config.is_verbose_mode_enabled)
        return mix
