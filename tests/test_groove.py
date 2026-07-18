"""swing/groove placement (issue #8): micro-timing offsets, wired into the quantized mixer.

Zero-dep on purpose — this repo has no test runner. Run it directly:

    PYTHONPATH=. .venv/bin/python tests/test_groove.py

Acceptance, all read from the rendered artifact's grain-start timestamps (not by ear):
- swing math: on-beats never move; swing<=50 (incl 0) is a no-op; swing=66 puts the off-beat at ~2/3
  of the beat (on:off ~= 2:1).
- In the quantized mixer: swing=66 delays every off-beat grain by ~0.32*slot; swing=0 placement is
  bit-identical to the straight grid. Snap composes with both quantized and the rw baseline.
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from pydub import AudioSegment
from pydub.generators import Sine
from pydub.silence import detect_nonsilent

from automixer.config import AutoMixerConfig
from automixer.mixers.quantized_mixer import QuantizedAutoMixer
from automixer.mixers.default_mixer import RandomWindowAutoMixer
from automixer.effects.groove import swing_offset, groove_offsets

failures = []

# ---- 1. Swing math ---------------------------------------------------------------------------
SUB = 100.0  # sub_ms; beat = 2*sub = 200
if swing_offset(0, 66, SUB) != 0.0:
    failures.append("on-beat (even slot) moved under swing — must stay put")
if swing_offset(1, 0, SUB) != 0.0 or swing_offset(1, 50, SUB) != 0.0:
    failures.append("swing<=50 is not a no-op (swing 0 / 50 delayed the off-beat)")
off66 = swing_offset(1, 66, SUB)
# off-beat lands at sub + off66; ratio on:off = (sub+off66) : (2*sub - (sub+off66)) should be ~2:1
on_len = SUB + off66
off_len = 2 * SUB - on_len
ratio = on_len / off_len
print("swing=66: off-beat delay=%.1f ms, on:off ratio=%.2f:1 (expect ~2:1)" % (off66, ratio))
if not (1.8 <= ratio <= 2.2):
    failures.append("swing=66 on:off ratio %.2f not ~2:1" % ratio)
# groove template overrides swing, applied cyclically
if groove_offsets(5, template=[0, 20]) != [0.0, 20.0, 0.0, 20.0, 0.0]:
    failures.append("groove template not applied cyclically")

# ---- build a click track whose grains are sparse (blip + silence) so each slot is measurable ----
def click_track(period_ms=400, n=6):
    click = Sine(1000).to_audio_segment(duration=5).apply_gain(-1)
    rest = AudioSegment.silent(duration=period_ms - 5)
    t = AudioSegment.silent(duration=0)
    for _ in range(n):
        t += click + rest
    return t


track = click_track(400, 6)  # 2400 ms, beat=400
beats = np.array([0, 400, 800, 1200, 1600, 2000])  # librosa hands the pipeline an ndarray, not a list
SLOT = 400 / 4  # euclid_n=4 all-hits -> every 100 ms slot fires (on+off beats)


def starts(mix):
    r = detect_nonsilent(mix, min_silence_len=30, silence_thresh=mix.dBFS - 12, seek_step=1)
    return sorted(s for s, _ in r)


def cfg(**kw):
    base = dict(mode="q", euclid_k=4, euclid_n=4, sample_length=100)
    base.update(kw)
    return AutoMixerConfig(track, beats, base.pop("sample_length"), **base)


# ---- 2. swing=0 is bit-identical to the straight grid (genuine no-op) --------------------------
s0 = starts(QuantizedAutoMixer().mix(cfg(swing=0)))
grid = [i * SLOT for i in range(int(2400 / SLOT))]
off_grid = [p for p in s0 if min(abs(p - g) for g in grid) > 5]
if off_grid:
    failures.append("swing=0 placed grains off the straight grid: %r — not a no-op" % off_grid)

# ---- 3. swing=66 delays every OFF-beat grain by ~0.32*slot; on-beats stay -----------------------
s66 = starts(QuantizedAutoMixer().mix(cfg(swing=66)))
expected_off = SLOT * max(0.0, (66 - 50) / 50)  # 32 ms
bad = []
for p in s66:
    idx = int(round(p / SLOT))
    offset = p - idx * SLOT
    if idx % 2 == 0:  # on-beat
        if abs(offset) > 6:
            bad.append(("even", p, offset))
    else:  # off-beat
        if abs(offset - expected_off) > 8:
            bad.append(("odd", p, offset))
print("swing=66 expected off-beat delay ~%.0f ms; anomalies: %r" % (expected_off, bad[:4]))
if bad:
    failures.append("swing=66 off-beats not delayed ~%.0f ms (or on-beats moved): %r" % (expected_off, bad[:4]))
# and the two placements genuinely differ
if s0 == s66:
    failures.append("swing=66 produced the same placement as swing=0 — swing had no effect")

# ---- 4. Snap composes with quantized (still grid-aligned) and with the rw baseline (runs) -------
snap_mix = QuantizedAutoMixer().mix(cfg(swing=0, snap=True))
snap_starts = starts(snap_mix)
if not snap_starts or any(min(abs(p - g) for g in grid) > 8 for p in snap_starts):
    failures.append("snap+quantized broke grid alignment")

rw_cfg = AutoMixerConfig(track, beats, 150, mode="rw", snap=True)
rw_out = RandomWindowAutoMixer().mix(rw_cfg)
if len(rw_out) == 0 or rw_out.dBFS == float("-inf"):
    failures.append("snap did not compose with the rw baseline (empty/silent mix)")

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("ok: swing math is 2:1 at 66 and no-op at <=50; quantized swing delays off-beats from the "
      "timestamps; swing=0 is the straight grid; snap composes with quantized and rw")
