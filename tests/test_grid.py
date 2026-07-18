"""grid: euclidean rhythm patterns + beat-subdivision slot grid.

Zero-dep on purpose — this repo has no test runner. Run it directly:

    PYTHONPATH=. .venv/bin/python tests/test_grid.py

The quantized mixer (issue #5) places grains on an explicit subdivision grid driven by a
euclidean pattern E(k, n) instead of the rw mixer's random pick. These are the pure-math
gates: the pattern must be the CANONICAL Bjorklund rotation (E(3,8) is the tresillo with hits
at slots 0,3,6 — not merely "3 hits somewhere in 8"), and the slot grid must land on exact
beat subdivisions.
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from automixer.iterators.grid import euclidean, grid_slots

failures = []


def hits(pattern):
    return [i for i, v in enumerate(pattern) if v]


# 1. E(3,8) is the tresillo: hits at 0,3,6 — the canonical Bjorklund rotation, not a shift of it.
p = euclidean(3, 8)
if p != [1, 0, 0, 1, 0, 0, 1, 0]:
    failures.append("euclidean(3,8) -> %r; expected the tresillo [1,0,0,1,0,0,1,0] (hits 0,3,6)" % p)

# 2. E(5,8) is the cinquillo: hits at 0,2,3,5,6.
p = euclidean(5, 8)
if p != [1, 0, 1, 1, 0, 1, 1, 0]:
    failures.append("euclidean(5,8) -> %r; expected the cinquillo [1,0,1,1,0,1,1,0] (hits 0,2,3,5,6)" % p)

# 3. E(4,4) is a straight four-on-the-floor; E(1,4) is one hit on the downbeat.
if euclidean(4, 4) != [1, 1, 1, 1]:
    failures.append("euclidean(4,4) -> %r; expected all hits" % euclidean(4, 4))
if euclidean(1, 4) != [1, 0, 0, 0]:
    failures.append("euclidean(1,4) -> %r; expected one hit on the downbeat" % euclidean(1, 4))

# 4. Every pattern has exactly k hits over n slots, and hits are spread as evenly as the integers
#    allow (max gap - min gap <= 1 — the defining property of a euclidean rhythm).
for k, n in [(3, 8), (5, 8), (2, 5), (5, 13), (7, 16), (4, 9)]:
    p = euclidean(k, n)
    if len(p) != n:
        failures.append("euclidean(%d,%d) length %d != %d" % (k, n, len(p), n))
        continue
    if sum(p) != k:
        failures.append("euclidean(%d,%d) has %d hits, expected %d" % (k, n, sum(p), k))
        continue
    h = hits(p)
    if len(h) >= 2:
        gaps = [(h[(i + 1) % len(h)] - h[i]) % n for i in range(len(h))]
        if max(gaps) - min(gaps) > 1:
            failures.append("euclidean(%d,%d) gaps %r not evenly spread (max-min>1)" % (k, n, gaps))

# 5. Degenerate cases don't crash: k=0 -> all rests, k>=n -> all hits, n=0 -> empty.
if euclidean(0, 4) != [0, 0, 0, 0]:
    failures.append("euclidean(0,4) -> %r; expected all rests" % euclidean(0, 4))
if euclidean(9, 4) != [1, 1, 1, 1]:
    failures.append("euclidean(9,4) (k>n) -> %r; expected clamp to all hits" % euclidean(9, 4))
if euclidean(3, 0) != []:
    failures.append("euclidean(3,0) -> %r; expected empty" % euclidean(3, 0))

# 6. grid_slots tiles the pattern across a span and returns the OUTPUT ms position of each HIT.
#    beat_period=400ms, n=8 -> slot=50ms. Pattern E(3,8) hits at slots 0,3,6 per beat.
#    Over 2 beats (800ms) the hit slot indices are 0,3,6, 8,11,14 -> ms 0,150,300, 400,550,700.
slots = grid_slots(beat_period=400.0, pattern=euclidean(3, 8), total_ms=800.0)
expected = [0.0, 150.0, 300.0, 400.0, 550.0, 700.0]
if [round(s, 3) for s in slots] != expected:
    failures.append("grid_slots(400,E(3,8),800) -> %r; expected %r" % (slots, expected))

# 7. grid_slots is deterministic — same inputs, same slots, every call.
if grid_slots(400.0, euclidean(3, 8), 800.0) != grid_slots(400.0, euclidean(3, 8), 800.0):
    failures.append("grid_slots is not deterministic")

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("ok: euclidean is canonical Bjorklund; grid_slots lands on exact beat subdivisions")
