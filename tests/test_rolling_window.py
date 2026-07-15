"""rolling_window: a window is at least one beat.

Zero-dep on purpose — this repo has no test runner. Run it directly:

    PYTHONPATH=. .venv/bin/python tests/test_rolling_window.py

Regression 2026-07-15: `len(iterable) // window_divider` floored to 0 whenever the divider exceeded
the beat count, tee(iterable, 0) came back empty, and `zip()` over no iterators yielded nothing. The
mix came out empty, main.py wrote a 261-byte mp3 and exited 0 — a total failure wearing a success rc
and a plausible artifact.

Why it stayed hidden: the grind lane was ear-only (the ledger's global line-retention flushed every
other organ out before it could be ranked), and the ear's 18s buffer measures 25-47 beats, so every
divider in the reflex's pool [4, 5, 6, 8] sat safely under it. The first non-ear record ever to be
ground was a 4.97s soundscape measuring 5 beats — and half the pool floored to zero.
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from automixer.iterators.rolling_window import rolling_window

W_POOL = [4, 5, 6, 8]           # the divider pool mesh-sound-reflex rotates over
FIVE_BEATS = [100, 200, 300, 400, 500]   # what the automixer finds in a ~5s soundscape

failures = []

# 1. No divider in the pool may silently yield nothing, however short the source.
for w in W_POOL:
    n = len(list(rolling_window(FIVE_BEATS, w)))
    if n == 0:
        failures.append(
            "rolling_window(%d beats, w=%d) yielded NO windows — the mix is empty and main.py "
            "still saves an mp3 and exits 0" % (len(FIVE_BEATS), w)
        )

# 2. The degenerate boundary itself: a divider larger than the beat count clamps to one beat per
#    window rather than flooring to zero. w=6 and w=8 over 5 beats must behave like w=5, not vanish.
for w in (6, 8, 99):
    got = list(rolling_window(FIVE_BEATS, w))
    if len(got) != len(FIVE_BEATS) or any(len(win) != 1 for win in got):
        failures.append(
            "rolling_window(5 beats, w=%d) -> %r; a divider finer than one-beat-per-window must "
            "clamp to one beat per window" % (w, got)
        )

# 3. The normal case must not have moved: a divider under the beat count still groups beats.
got = list(rolling_window(list(range(20)), 4))
if not got or len(got[0]) != 5:
    failures.append("rolling_window(20 beats, w=4) -> window size %s, expected 5 (20//4)"
                    % (len(got[0]) if got else "no windows"))

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("ok: rolling_window never yields an empty mix; short sources clamp to one beat per window")
