"""Bit-identity contract for the low-memory renderer path (2026-07-19).

The rw mixer's ``low_memory=True`` path streams raw bytes into a single ``bytearray`` instead of
accumulating a list of ``AudioSegment`` wrappers and joining at the end. The two paths MUST produce
byte-identical output (both reduce to ``first._spawn(joined_bytes)``); a drift here would silently
change every cron-driven grind (which now runs under ``--low-memory`` to fit the cgroup budget).

This test is the fail-safe for the refactor: it runs the SAME seeded config through both paths and
asserts the ``raw_data`` + attrs match exactly. If this fails after a low_memory-path edit, the edit
changed the bytes — fix it, do not weaken the assertion.

(pytest-discoverable; collected by ``pytest tests/``.)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _bit_identity import build_source, build_beats, fingerprint
from automixer.config import AutoMixerConfig, ChannelConfig
from automixer.runner import AutoMixerRunner


def _rw_config(low_memory, seed=0):
    src = build_source()
    beats = build_beats()
    return AutoMixerConfig(
        src, beats,
        sample_length=120,
        mode="rw",
        sample_speed=1.3,
        speed=1.1,
        window_divider=4,
        channels_config=[ChannelConfig(80, 2000), ChannelConfig(2000, 12000)],
        seed=seed,
        low_memory=low_memory,
    )


def test_low_memory_path_matches_default_bit_for_bit():
    """The low-memory streaming path MUST be byte-identical to the default list-accumulate path
    on the SAME seeded config — same raw_data bytes, same frame_rate/sample_width/channels/
    frame_count. Anything else is a behaviour change hiding behind a memory fix."""
    default = AutoMixerRunner().run(_rw_config(low_memory=False))
    lowmem = AutoMixerRunner().run(_rw_config(low_memory=True))
    assert fingerprint(default) == fingerprint(lowmem), (
        "low_memory path drifted from default:\n"
        f"  default: {fingerprint(default)}\n"
        f"  lowmem:  {fingerprint(lowmem)}\n"
        "The low-memory streaming path must be byte-identical to the list-accumulate path."
    )


def test_low_memory_empty_source_renders_empty():
    """An empty source (no beats → no windows → empty mix) must render to AudioSegment.empty()
    on both paths, not crash on a None ``first`` reference or raise in the bytearray concat."""
    import numpy as np
    from pydub import AudioSegment
    empty_audio = AudioSegment.silent(duration=0)
    empty_beats = np.array([], dtype=int)
    cfg = AutoMixerConfig(
        empty_audio, empty_beats,
        sample_length=120, mode="rw", window_divider=4,
        channels_config=[ChannelConfig(0, 15000, bypass=True)],
        low_memory=True,
    )
    out = AutoMixerRunner().run(cfg)
    assert len(out) == 0, f"low_memory empty-source path should render empty, got len={len(out)}"
