"""Perf regression gate for the optimization pass (2026-07-19).

The bit-identity test (`test_bit_identity.py`) locks the OUTPUT; this test guards the SPEED —
landed optimizations stay landed, and a regression that re-introduces an O(n^2) concat or an
accidental pydub round-trip fails here before it ships.

Source: the canonical 3.2s deterministic signal from `_bit_identity.build_source` — short enough
that the whole test runs in ~2s on the baseline machine, long enough that the per-grain work is
non-trivial. Budgets are 3x the measured baseline median (loose enough not to flake on a slow CI
box, tight enough that a 2x regression fails loudly). Tune via env:

    GRAINNEUKELN_PERF_BUDGET_MULT=2.0   # tighten the budgets (smaller multiplier)
    GRAINNEUKELN_PERF_SKIP=1            # skip the whole gate (e.g. on a known-slow CI runner)

The bench script (`scripts/bench.py`) is the right tool for DEEP profiling on long sources — this
test is just the regression tripwire. Run bench.py before/after any perf change to see the actual
delta; this test only enforces "no regression past the budget".
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import pytest

from _bit_identity import each_mode_config
from automixer.runner import AutoMixerRunner

# 3x the baseline median, env-tunable. The baseline numbers (median of 3 runs on the dev machine,
# 2026-07-19) are recorded inline so the budget math is auditable; the multiplier is what actually
# bounds the test, and shrinking it is the lever for tightening after a win lands.
#
# Two columns: PRE = pre-refactor (concat/overlay was O(L²)), POST = after the bit-identical C/F
# pass (concat/overlay now O(n); band_pass_filer is still the ~87% wall on the BPF-on path).
# On the SHORT 3.2s source the C/F wins are small (the band-pass dominates at every length); on
# the 30s long source BPF-on rw went 28.7s → 27s, q 3.4s → 3.0s, poly 5.8s → 5.6s, lib 2.75s → 2.8s.
# BPF-OFF (the bypass default, landed 2026-07-19) skips band_pass_filer entirely — 4-5x faster
# across all modes on the 30s source (rw 27s → 6s, q 2.8s → 0.8s, poly 5.7s → 1.2s, lib 2.6s → 0.6s).
# The architectural wins are real and locked by these budgets.
_MULT = float(os.environ.get("GRAINNEUKELN_PERF_BUDGET_MULT", "3.0"))

_BASELINE_SEC_BPF_ON = {
    # measured 2026-07-19 on /home/mesh-home/grainneukeln (3.2s canonical source, median of 3):
    "rw":   0.336,   # post: 0.318 (-5%)
    "q":    0.377,   # post: 0.362 (-4%)
    "poly": 0.633,   # post: 0.674 (+6% on short — canvas setup overhead at 3.2s, pays off at 30s)
    "lib":  0.313,   # post: 0.300 (-4%)
}

_BASELINE_SEC_BPF_OFF = {
    # BPF-off (bypass default) — captured 2026-07-19 after the bypass landed, measured short-source
    # medians. Sub-200ms per mode because band_pass_filer (the 87% wall) is skipped entirely. The
    # budgets are 3x these medians — still well under a second per mode, so the test stays fast.
    "rw":   0.067,
    "q":    0.150,
    "poly": 0.161,
    "lib":  0.066,
}


@pytest.mark.parametrize("mode", ["rw", "q", "poly", "lib"])
@pytest.mark.parametrize("bpf", [True, False], ids=["bpf-on", "bpf-off"])
def test_perf_no_regression(mode, bpf):
    if os.environ.get("GRAINNEUKELN_PERF_SKIP"):
        pytest.skip("GRAINNEUKELN_PERF_SKIP set")

    # Pull the matching config from the shared harness so this test stays in lockstep with the
    # bit-identity fixtures — same source, same params, same seed.
    cfg = next(cfg for lab, cfg in each_mode_config(seed=0, bpf=bpf) if lab.startswith(mode))

    # Single run — the bench script does the multi-run profiling; this is a tripwire, not a benchmark.
    t0 = time.perf_counter()
    AutoMixerRunner().run(cfg)
    dt = time.perf_counter() - t0

    baseline = _BASELINE_SEC_BPF_OFF[mode] if not bpf else _BASELINE_SEC_BPF_ON[mode]
    budget = baseline * _MULT
    bpf_label = "bpf-off" if not bpf else "bpf-on"
    assert dt <= budget, (
        f"{mode} [{bpf_label}] render took {dt:.3f}s, budget {budget:.3f}s "
        f"(baseline {baseline:.3f}s × {_MULT}). "
        f"Regression, or tighten the budget if an optimization landed — "
        f"run `scripts/bench.py` for the full picture."
    )
