"""snap-to-length (issue #8): pitch-preserving stretch of a grain to a target slot length.

Zero-dep on purpose — this repo has no test runner. Run it directly:

    PYTHONPATH=. .venv/bin/python tests/test_snap.py

Acceptance: a grain cut to 0.7x a beat, snapped to the beat, lands within a few ms of the slot AND
keeps its pitch (assert the spectral centroid is stable, not just the duration). snap-to-own-length
is a genuine no-op (bit-identical).
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from pydub.generators import Sine

from automixer.effects.change_tempo import snap_to_length

failures = []


def centroid(seg):
    import librosa
    y = np.array(seg.get_array_of_samples()).astype(np.float32)
    if seg.channels == 2:
        y = y.reshape((-1, 2)).mean(axis=1)
    peak = np.max(np.abs(y)) if y.size else 0.0
    if peak > 0:
        y = y / peak
    return float(np.mean(librosa.feature.spectral_centroid(y=y, sr=seg.frame_rate)))


BEAT = 400
# A 300 Hz grain deliberately cut to 0.7x a beat (280 ms) — off-length, would smear the groove.
grain = Sine(300).to_audio_segment(duration=int(BEAT * 0.7))
before_ms = len(grain)
before_cen = centroid(grain)

snapped = snap_to_length(grain, BEAT)
after_ms = len(snapped)
after_cen = centroid(snapped)

print("duration: %d ms -> %d ms (target %d)" % (before_ms, after_ms, BEAT))
print("centroid: %.1f Hz -> %.1f Hz" % (before_cen, after_cen))

# 1. Duration snaps to the slot within a few ms.
if abs(after_ms - BEAT) > 5:
    failures.append("snapped duration %d ms is not within 5 ms of the %d ms slot" % (after_ms, BEAT))

# 2. Pitch is unchanged — the centroid moves by well under a semitone (~6%). A speed change (no
#    pitch preservation) would have shifted 300 Hz -> ~214 Hz (a fifth+), a >25% move.
drift = abs(after_cen - before_cen) / before_cen
if drift > 0.08:
    failures.append("centroid drifted %.1f%% (%.0f->%.0f Hz) — pitch not preserved by the stretch"
                    % (drift * 100, before_cen, after_cen))

# 3. Snapping to the current length is a genuine no-op (bit-identical).
noop = snap_to_length(grain, len(grain))
if noop.raw_data != grain.raw_data:
    failures.append("snap_to_length(seg, len(seg)) altered the audio — not a no-op")

# 4. Stretch SHORTER too (grain cut to 1.4x a beat -> snap down), pitch still stable.
long_grain = Sine(300).to_audio_segment(duration=int(BEAT * 1.4))
short = snap_to_length(long_grain, BEAT)
if abs(len(short) - BEAT) > 5:
    failures.append("snapping a 1.4x grain down to the slot missed: %d ms" % len(short))
if abs(centroid(short) - before_cen) / before_cen > 0.08:
    failures.append("pitch drifted snapping DOWN to the slot")

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("ok: snap stretches a grain to the slot length within a few ms, pitch preserved, no-op when already on length")
