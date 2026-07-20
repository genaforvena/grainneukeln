"""beat_grid_floor: rescue a degenerate onset detection with a uniform grid.

Zero-dep on purpose — this repo has no test runner. Run it directly:

    PYTHONPATH=. .venv/bin/python tests/test_beat_grid_floor.py

librosa.beat_track locks a SINGLE beat onto ambient/beatless material (a note3 room
recording, speech) where there is no pulse to find. The rw mixer places one window per
detected beat, so a 1-beat read collapsed an 11.8s source to a ~0.2s grind that the
downstream hollow gate then rejected — the mesh-sound-reflex skip:hollow storm of
2026-07-20 (every 1-beat note3 record). beat_grid_floor replaces a too-sparse detection
with an evenly-spaced grid spanning the whole source (the 'rhythm-seeking regime' the
poly/library mixers already embrace) so beatless input still grinds full-length; genuine
rhythm is left untouched.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from automixer.utils import beat_grid_floor

failures = []

# 1. THE BUG: a single detected beat over an 11.8s source is floored to a real grid.
#    (RED before the fix: a 1-beat detection stayed length 1 -> ~0.2s hollow grind.)
g = beat_grid_floor(np.array([5000]), 11800)
if len(g) < 4:
    failures.append("1-beat/11.8s floored to only %d slots; expected a full grid (>=4)" % len(g))
if len(g) and (g[0] != 0 or g[-1] > 11800):
    failures.append("grid must span [0, duration): got first=%s last=%s over 11800ms" % (g[0], g[-1]))
# evenly spaced (a real grid, not clustered)
if len(g) >= 3:
    diffs = np.diff(g)
    if diffs.max() - diffs.min() > 1:
        failures.append("grid not evenly spaced: diffs %r" % diffs.tolist())

# 2. GENUINE RHYTHM IS UNTOUCHED: a dense detection passes through byte-for-byte.
dense = np.array([0, 480, 950, 1430, 1900, 2380, 2850])  # 7 beats
out = beat_grid_floor(dense, 11800)
if not np.array_equal(out, dense):
    failures.append("dense (7-beat) input must pass through unchanged; got %r" % out.tolist())

# 3. THE THRESHOLD IS min_beats=4: exactly 4 real beats is kept (clears the hollow gate at
#    ~1.7s on its own); 3 is floored. This is the observed cliff (1-beat 0.2s, 4-beat 1.69s).
four = np.array([100, 600, 1100, 1600])
if not np.array_equal(beat_grid_floor(four, 11800), four):
    failures.append("exactly min_beats(4) must be kept, not gridded")
if len(beat_grid_floor(np.array([100, 600, 1100]), 11800)) <= 3:
    failures.append("3 beats (< min_beats) must be floored to a grid, not kept")

# 4. A source too short to grid meaningfully is left alone (no rescue that produces < 2 slots).
short = np.array([100])
if not np.array_equal(beat_grid_floor(short, 600), short):
    failures.append("a sub-2-period source must be returned unchanged, not gridded")

# 5. Custom cadence: a 250ms grid over 2000ms yields 8 slots at 0,250,...,1750.
g2 = beat_grid_floor(np.array([1]), 2000, grid_period_ms=250)
if list(g2) != [0, 250, 500, 750, 1000, 1250, 1500, 1750]:
    failures.append("grid_period_ms=250 over 2000ms -> %r; expected 8 slots" % list(g2))

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("ok: beatless detection floored to a full grid; genuine rhythm untouched (min_beats=4)")
