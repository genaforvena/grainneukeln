"""Shared harness for the bit-identity contract (perf optimization 2026-07-19).

Every perf-only change to the renderers MUST leave `AudioSegment.raw_data` byte-identical for a
seeded config. This module owns:

- `build_source()`: the canonical deterministic source the fixtures were captured against.
- `each_mode_config(seed)`: yields (mode_name, AutoMixerConfig) pairs covering all four mixers.
- `fingerprint(seg)`: a stable hash of the rendered mix (bytes + the attrs that must not drift).
- `load_fixture(mode)` / `save_fixture(mode, seg)`: read/write the committed baseline.

Fixtures live in `tests/fixtures/<mode>_seed0.txt` as plain text (sha256 + metadata), so a diff is
readable in code review and a regeneration is an obvious commit. They are captured ONCE from the
pre-refactor code and committed; any later change that alters the fingerprint must be (a) intentional,
(b) re-blessed via `regenerate`, and (c) audible-character-checked — not a silent drift.

Usage in tests/test_bit_identity.py:
    from _bit_identity import each_mode_config, fingerprint, load_fixture
    for mode, cfg in each_mode_config(seed=0):
        seg = AutoMixerRunner().run(cfg)
        assert fingerprint(seg) == load_fixture(mode), f"{mode} drifted"

Regenerate after an intentional blessed change:
    PYTHONPATH=. .venv/bin/python tests/_bit_identity.py regenerate
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from pydub import AudioSegment
from pydub.generators import Sine

from automixer.config import AutoMixerConfig, ChannelConfig
from automixer.runner import AutoMixerRunner

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
CANONICAL_SEED = 0


def _warm_jit():
    """Force numba JIT compilation of librosa.effects.time_stretch (and its transitive callees)
    BEFORE any seeded render. The first call in a process uses pure-Python fallback and produces
    subtly different float-rounded output than the JIT-compiled path used on every subsequent call
    — bit-identical seeded output requires the JIT to be warm before the first seeded run. Also
    primes a tiny onset_detect + beat_track so any other first-call JIT paths are warm too."""
    import librosa
    y = np.zeros(2205, dtype=np.float32)            # 100ms of silence at 22050Hz
    y[::200] = 0.5                                   # sparse transients for onset_detect to find
    librosa.effects.time_stretch(y, rate=1.0)
    librosa.onset.onset_detect(y=y, sr=22050)
    librosa.beat.beat_track(y=y, sr=22050)


_warm_jit()

def build_source():
    """The canonical deterministic source: an 8-click track (4ms 1kHz blip every 400ms) over a
    continuous 200Hz bed. Clicks give beat_track + onset_detect real transients to lock onto (so
    every mixer has grist); the bed gives the band-pass + remnant-fill material something to chew
    on (silent sources render identically regardless of optimization). 3.2s long — short enough for
    a sub-second baseline, long enough that the O(n^2) shape is measurable in the bench."""
    bed = Sine(200).to_audio_segment(duration=3200).apply_gain(-20)
    click = Sine(1000).to_audio_segment(duration=4).apply_gain(-1)
    clicks = AudioSegment.silent(duration=0)
    for _ in range(8):
        clicks += click + AudioSegment.silent(duration=396)
    return bed.overlay(clicks)


def build_beats():
    """Beat positions matching the source (every 400ms for 8 beats), as an int numpy array — the
    shape ``sample_cut_tool._detect_beats`` produces downstream of librosa."""
    return (np.arange(8) * 400).astype(int)


def each_mode_config(seed=CANONICAL_SEED, bpf=True):
    """Yield (label, AutoMixerConfig) for every mixer.

    ``bpf=True`` (default) uses two explicit band-pass channels (the slow path, BPF applied per
    grain) — these are the original bit-identity fixtures.

    ``bpf=False`` uses one bypass channel (raw pass-through, no band_pass_filer call) — the
    4-5× faster default path landed 2026-07-19. Fixtures for this path lock the no-BPF behaviour
    so a future change to the bypass short-circuit can't drift silently.

    The ``label`` encodes the path so fixture files don't collide: ``rw``, ``q``, ``poly``,
    ``lib`` for BPF-on; ``rw_nobpf``, ``q_nobpf``, ``poly_nobpf``, ``lib_nobpf`` for BPF-off.

    Each config exercises its mode's hot path with non-trivial work: the mode's signature params,
    sample_speed to trigger the per-grain phase vocoder, and whole-mix speed for rw/poly (q/lib
    don't compose well with whole-mix stretch but the runner applies it regardless when set; we
    leave s=1.0 for those)."""
    src = build_source()
    beats = build_beats()
    if bpf:
        channels = [ChannelConfig(80, 2000), ChannelConfig(2000, 12000)]
    else:
        channels = [ChannelConfig(0, 15000, bypass=True)]
    suffix = "" if bpf else "_nobpf"

    # env_pct=0 pins every fixture config to the pre-2026-07-21 hard-cut boundary (grain envelope
    # feature landed with a non-zero default of 8.0) -- these fixtures compare against a COMMITTED
    # golden byte string (tests/fixtures/<mode>_seed0.txt), not a live render on the other side, so
    # the new always-on-unless-zeroed envelope would otherwise drift every one of them. reverse_prob
    # stays at its 0.0 default: `maybe_reverse` short-circuits before touching the RNG when prob<=0,
    # so it draws exactly as many random numbers as before the feature existed and cannot drift the
    # byte-identity contract on its own.
    configs = [
        ("rw", AutoMixerConfig(
            src, beats, sample_length=120, mode="rw", sample_speed=1.3, speed=1.1,
            window_divider=4, channels_config=channels, seed=seed, env_pct=0)),
        ("q", AutoMixerConfig(
            src, beats, sample_length=120, mode="q", euclid_k=3, euclid_n=8,
            channels_config=channels, sample_speed=1.2, fill=True, seed=seed, env_pct=0)),
        ("poly", AutoMixerConfig(
            src, beats, sample_length=120, mode="poly", sample_speed=1.2, speed=1.05,
            streams=[{"ratio": 4}, {"ratio": 3}], channels_config=channels, seed=seed, env_pct=0)),
        ("lib", AutoMixerConfig(
            src, beats, sample_length=120, mode="lib", lib_policy="contrast", lib_clusters=4,
            channels_config=channels, sample_speed=1.2, seed=seed, env_pct=0)),
    ]
    for mode, cfg in configs:
        yield mode + suffix, cfg


def fingerprint(seg):
    """A stable identity for the rendered mix. Includes sha256 of `_data` AND the attrs that must
    not drift (frame_rate/sample_width/channels/frame_count) — a refactor that resamples or widens
    the sample format would silently keep the same bytes-don't-match story otherwise. dBFS is NOT
    included because the normalize_loudness stage runs at export, not in the renderer under test."""
    if seg is None:
        return "none"
    h = hashlib.sha256()
    h.update(seg.raw_data)
    meta = (f"sr={seg.frame_rate}|sw={seg.sample_width}|ch={seg.channels}"
            f"|fc={seg.frame_count()}|len={len(seg)}")
    h.update(meta.encode())
    return h.hexdigest() + " " + meta


def fixture_path(mode):
    return os.path.join(FIXTURE_DIR, f"{mode}_seed{CANONICAL_SEED}.txt")


def save_fixture(mode, seg):
    fp = fingerprint(seg)
    with open(fixture_path(mode), "w") as f:
        f.write(fp + "\n")
    return fp


def load_fixture(mode):
    p = fixture_path(mode)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return f.read().strip()


def regenerate():
    """Re-capture every fixture from the current code. Only run this when an intentional blessed
    change has been made AND audibly checked — never as a 'make the test pass' reflex."""
    # Both BPF-on (filtered) and BPF-off (bypass) paths — locks both behaviours.
    for bpf in (True, False):
        for label, cfg in each_mode_config(bpf=bpf):
            seg = AutoMixerRunner().run(cfg)
            fp = save_fixture(label, seg)
            print(f"  {label}: {fp}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "regenerate":
        print("Regenerating bit-identity fixtures from current code:")
        regenerate()
        print("Done. Inspect the diff before committing.")
    else:
        print("Usage: regenerate   # re-capture all fixtures")
        sys.exit(1)
