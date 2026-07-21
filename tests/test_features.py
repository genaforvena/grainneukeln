"""features (issue #7): per-grain measurement, corpus-calibrated axes, clustering.

Zero-dep on purpose — this repo has no test runner. Run it directly:

    PYTHONPATH=. .venv/bin/python tests/test_features.py

Two mesh-doctrine gates: (1) feature axes are rank-calibrated against the ACTUAL grain set so an axis
cannot saturate/constant-out (memory: tone pinned at 1.0 became a dead constant); (2) the
rhythm-density measure discriminates dense rhythmic material from an isolated impulse.
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from pydub import AudioSegment
from pydub.generators import Sine, WhiteNoise

from automixer.features import measure_grain, calibrate, cluster, AXES

failures = []

# ---- 1. Calibration spreads a raw-saturated axis across [0,1] (cannot constant-out) ------------
# centroid values look saturated near the top (four near-max, one low) — rank calibration must still
# map min->0, max->1 and separate the low one, instead of collapsing to a constant.
raw = [
    {"centroid": 1.0, "rms": 0.5, "rhythm_density": 2.0, "hpss_ratio": 0.5},
    {"centroid": 1.0, "rms": 0.4, "rhythm_density": 2.0, "hpss_ratio": 0.6},
    {"centroid": 0.99, "rms": 0.3, "rhythm_density": 2.0, "hpss_ratio": 0.4},
    {"centroid": 0.98, "rms": 0.2, "rhythm_density": 2.0, "hpss_ratio": 0.3},
    {"centroid": 0.20, "rms": 0.1, "rhythm_density": 2.0, "hpss_ratio": 0.7},
]
norm = calibrate(raw)
cen = norm[:, AXES.index("centroid")]
# The unique min value maps to 0; the axis spreads across most of [0,1] (a tied max lands below 1.0
# by tie-averaging — identical grains get identical calibrated values, which is correct). The point
# is that the raw-saturated axis is NOT collapsed to a constant.
if abs(cen.min() - 0.0) > 1e-9:
    failures.append("calibrated centroid min %.3f != 0 — the lowest grain must anchor the axis" % cen.min())
if cen.max() < 0.8 or (cen.max() - cen.min()) < 0.8:
    failures.append("calibrated centroid spread only %.3f — saturated axis collapsed toward constant" % (cen.max() - cen.min()))
if cen[4] >= cen[3]:
    failures.append("calibration did not separate the low-centroid grain from the saturated cluster")
# A truly constant axis (rhythm_density all 2.0) carries no information -> contributes ~0 spread,
# NOT a fake gradient. (This is the correct behavior: dead axis stays dead, live axes stay live.)
rd = norm[:, AXES.index("rhythm_density")]
if rd.std() > 1e-9:
    failures.append("a constant raw axis produced spread %.4f — calibration invented information" % rd.std())

# ---- 2. rhythm-density discriminates dense rhythmic material from an isolated impulse ----------
def impulse_clip(dur_ms=2000):
    click = Sine(1000).to_audio_segment(duration=8).apply_gain(-1)
    return click + AudioSegment.silent(duration=dur_ms - 8)  # ONE transient in 2 s


def dense_clip(dur_ms=2000, period_ms=70):
    click = Sine(1000).to_audio_segment(duration=8).apply_gain(-1)
    rest = AudioSegment.silent(duration=period_ms - 8)
    n = dur_ms // period_ms
    seg = AudioSegment.silent(duration=0)
    for _ in range(n):
        seg += click + rest
    return seg


imp = measure_grain(impulse_clip())["rhythm_density"]
dense = measure_grain(dense_clip())["rhythm_density"]
print("rhythm_density: impulse=%.3f b/s   dense=%.3f b/s" % (imp, dense))
if not (imp < 1.0):
    failures.append("impulse rhythm_density %.3f not low (<1.0) — measure does not read an isolated impulse as sparse" % imp)
if not (dense > imp + 1.0):
    failures.append("dense material rhythm_density %.3f not clearly above impulse %.3f — no discrimination" % (dense, imp))

# ---- 3. Clustering degrades honestly on too few grains (no crash, clamps k) --------------------
tiny = calibrate(raw[:2])
labels, cents = cluster(tiny, k=6)
if len(labels) != 2 or len(cents) > 2:
    failures.append("cluster(2 grains, k=6) -> %d labels, %d centroids; must clamp k to the grain count"
                    % (len(labels), len(cents)))

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("ok: axes calibrate against the corpus (no saturation), rhythm-density discriminates "
      "impulse from dense material, clustering clamps k honestly")
