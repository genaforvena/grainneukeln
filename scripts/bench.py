#!/usr/bin/env python3
"""Perf bench for the grainneukeln automixers (optimization pass 2026-07-19).

The bit-identity test locks output; this script measures wall-clock + cProfile per mode so every
optimization lands with a measured before/after. Run it on the SHORT canonical source by default
(matches the test fixture, sub-second baseline); add ``--long`` for a 30s source that exercises the
O(n^2) concat shape that bites on full tracks (rw on 30s was 28.7s pre-refactor).

Each mode runs N times (default 3); per-stage cProfile stats dump to ``bench/<mode>.prof`` for
``snakeviz`` / ``pstats`` inspection. Top-N hot functions print inline so the dominant cost is
visible without opening the prof file.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/bench.py             # short source, 3 runs/mode
    PYTHONPATH=. .venv/bin/python scripts/bench.py --long      # 30s source (the O(n^2) bite)
    PYTHONPATH=. .venv/bin/python scripts/bench.py --runs 5    # more samples
    PYTHONPATH=. .venv/bin/python scripts/bench.py --mode rw   # one mode only
"""
import argparse
import cProfile
import os
import pstats
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "tests")

import numpy as np
from pydub import AudioSegment
from pydub.generators import Sine

from automixer.config import AutoMixerConfig, ChannelConfig
from automixer.runner import AutoMixerRunner

import _bit_identity


def build_long_source(duration_ms=30000, period_ms=400):
    """A longer canonical source for the O(n^2) characterization: same shape as the bit-identity
    fixture (200Hz bed + 1kHz clicks every 400ms) but extended to ``duration_ms``. Clicks keep
    beat_track / onset_detect deterministic; the bed gives the band-pass + remnant-fill real signal
    to chew on so the per-grain work is non-trivial (silent sources are an unfair bench)."""
    bed = Sine(200).to_audio_segment(duration=duration_ms).apply_gain(-20)
    click = Sine(1000).to_audio_segment(duration=4).apply_gain(-1)
    n_clicks = duration_ms // period_ms
    clicks = AudioSegment.silent(duration=0)
    for _ in range(n_clicks):
        clicks += click + AudioSegment.silent(duration=period_ms - 4)
    src = bed.overlay(clicks)
    beats = (np.arange(n_clicks) * period_ms).astype(int)
    return src, beats


def long_configs(seed=0):
    src, beats = build_long_source()
    chs = [ChannelConfig(80, 2000), ChannelConfig(2000, 12000)]
    return [
        ("rw", AutoMixerConfig(
            src, beats, sample_length=120, mode="rw", sample_speed=1.3, speed=1.1,
            window_divider=4, channels_config=chs, seed=seed)),
        ("q", AutoMixerConfig(
            src, beats, sample_length=120, mode="q", euclid_k=3, euclid_n=8,
            channels_config=chs, sample_speed=1.2, fill=True, seed=seed)),
        ("poly", AutoMixerConfig(
            src, beats, sample_length=120, mode="poly", sample_speed=1.2, speed=1.05,
            streams=[{"ratio": 4}, {"ratio": 3}], channels_config=chs, seed=seed)),
        ("lib", AutoMixerConfig(
            src, beats, sample_length=120, mode="lib", lib_policy="contrast", lib_clusters=4,
            channels_config=chs, sample_speed=1.2, seed=seed)),
    ]


def median(xs):
    s = sorted(xs)
    return s[len(s) // 2]


def bench_one(mode, cfg, runs, out_dir):
    """Run a mode ``runs`` times under cProfile. Returns (median_wall_sec, pstats.Stats)."""
    wall_times = []
    prof = cProfile.Profile()
    # Warm the JIT / librosa import caches on the first run; profile the rest.
    AutoMixerRunner().run(cfg)
    for _ in range(runs):
        prof.enable()
        t0 = time.perf_counter()
        mix = AutoMixerRunner().run(cfg)
        wall_times.append(time.perf_counter() - t0)
        prof.disable()
    os.makedirs(out_dir, exist_ok=True)
    prof_path = os.path.join(out_dir, f"{mode}.prof")
    prof.dump_stats(prof_path)
    return median(wall_times), len(mix), pstats.Stats(prof), prof_path


def top_n(stats, n=10):
    """Top-N cumulative-time functions, clean-format. Thee default sort is cumulative so the
    OUTER frames (mix()) show their total cost — what you actually want when finding the hot loop."""
    lines = []
    stats.sort_stats("cumulative").print_stats(n)
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--long", action="store_true",
                    help="Use a 30s source (the O(n^2) bite) instead of the 3.2s canonical one.")
    ap.add_argument("--runs", type=int, default=3, help="Runs per mode (default 3, median reported).")
    ap.add_argument("--mode", default=None, help="One mode only (rw|q|poly|lib).")
    ap.add_argument("--top", type=int, default=10, help="Top-N hot functions to print.")
    ap.add_argument("--out", default="bench", help="Output dir for .prof files.")
    args = ap.parse_args()

    configs = long_configs(seed=0) if args.long else list(_bit_identity.each_mode_config(seed=0))
    if args.mode:
        configs = [(m, c) for m, c in configs if m == args.mode]
        if not configs:
            print(f"unknown mode: {args.mode}")
            return 1

    src_len = len(configs[0][1].audio) if configs else 0
    print(f"\n=== bench ({'long' if args.long else 'short'} source = {src_len}ms, "
          f"{args.runs} run(s)/mode, seed=0) ===\n")

    rows = []
    for mode, cfg in configs:
        med, out_ms, stats, prof_path = bench_one(mode, cfg, args.runs, args.out)
        rows.append((mode, med, out_ms, prof_path))
        print(f"--- {mode}: median {med:.3f}s  ->  {out_ms}ms output  (prof: {prof_path}) ---")
        top_n(stats, args.top)
        print()

    print("=== summary ===")
    print(f"{'mode':6s}  {'median':>8s}  {'output':>9s}")
    for mode, med, out_ms, _ in rows:
        print(f"{mode:6s}  {med:7.3f}s  {out_ms:6d}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
