import os
from datetime import datetime

from automixer.config import AutoMixerConfig, ChannelConfig
from automixer.runner import AutoMixerRunner
from cutter.sample_cut_tool import normalize_loudness


def build_config(cutter, state):
    """Map a SessionState onto the existing AutoMixerConfig. DSP untouched."""
    channels = [ChannelConfig(t.low, t.high) for t in state.tracks]
    return AutoMixerConfig(
        audio=cutter.audio,
        beats=cutter.beats,
        sample_length=state.sample_length_ms,
        sample_speed=state.sample_speed,
        mode="rw",
        speed=state.speed,
        is_verbose_mode_enabled=False,
        window_divider=state.window_divider,
        channels_config=channels,
    )


def run(config, out_dir, on_progress=None):
    """Render one grind and export an audible mp3. Returns the output path."""
    if on_progress:
        on_progress(0.0)
    os.makedirs(out_dir, exist_ok=True)
    mix = AutoMixerRunner().run(config)
    mix = normalize_loudness(mix)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(out_dir, f"grain_cut{int(config.sample_length)}_{stamp}.mp3")
    mix.export(path, format="mp3")
    if on_progress:
        on_progress(1.0)
    return path
