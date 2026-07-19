import os
from datetime import datetime

from automixer.config import AutoMixerConfig, ChannelConfig, parse_stream_spec
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
        mode=state.mode,
        speed=state.speed,
        is_verbose_mode_enabled=state.verbose,
        window_divider=state.window_divider,
        channels_config=channels,
        euclid_k=state.euclid_k,
        euclid_n=state.euclid_n,
        streams=parse_stream_spec(state.streams_spec),
        lib_policy=state.lib_policy,
        lib_clusters=state.lib_clusters,
        snap=state.snap,
        swing=state.swing,
        fill=state.fill,
        fill_gain_db=state.fill_gain_db,
    )


def run(config, out_dir, on_progress=None, wav_export=False):
    """Render one grind and export an audible mp3 (and optionally a WAV alongside).

    Returns the output mp3 path. WAV is written next to the mp3 when ``wav_export`` is set,
    matching the CLI's ``set_wav_enabled`` — the .mp3 is always written, the .wav is the extra.
    """
    if on_progress:
        on_progress(0.0)
    os.makedirs(out_dir, exist_ok=True)
    mix = AutoMixerRunner().run(config)
    mix = normalize_loudness(mix)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"grain_cut{int(config.sample_length)}_{stamp}"
    mp3_path = os.path.join(out_dir, base + ".mp3")
    mix.export(mp3_path, format="mp3")
    if wav_export:
        mix.export(os.path.join(out_dir, base + ".wav"), format="wav")
    if on_progress:
        on_progress(1.0)
    return mp3_path
