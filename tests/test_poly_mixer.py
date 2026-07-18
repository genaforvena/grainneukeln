"""poly mixer (issue #6): N parallel grain streams at different subdivisions, overlaid (Reich phasing).

Zero-dep on purpose — this repo has no test runner. Run it directly:

    PYTHONPATH=. .venv/bin/python tests/test_poly_mixer.py

Verification principle: the artifact, not the assertion. A 3-against-4 config is rendered and the
mixer hands back each stream as its own rendered ``AudioSegment``; the grain-start timestamps are read
back out of those segments (detect_nonsilent). The polyrhythm has to be visible in the timestamps:
stream A (ratio 4) fires every beat/4, stream B (ratio 3) every beat/3, they coincide every 12
subdivisions (LCM(3,4)), and both are simultaneously non-silent at the crossings in the combined mix
(genuinely layered, not concatenated).

O(n^2) note (memory grainneukeln-tui-and-venv): the mixer is O(n^2); test sources stay short (<55s).
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from pydub import AudioSegment
from pydub.generators import Sine, WhiteNoise
from pydub.silence import detect_nonsilent

from automixer.config import AutoMixerConfig, ChannelConfig
from automixer.mixers.poly_mixer import PolyphonicAutoMixer

failures = []


def click_track(period_ms=400, n=6):
    click = Sine(1000).to_audio_segment(duration=6).apply_gain(-1)
    rest = AudioSegment.silent(duration=period_ms - 6)
    track = AudioSegment.silent(duration=0)
    for _ in range(n):
        track += click + rest
    return track


def starts_of(seg, min_sil=25):
    if seg.dBFS == float("-inf"):
        return []
    regions = detect_nonsilent(seg, min_silence_len=min_sil, silence_thresh=seg.dBFS - 14, seek_step=1)
    return [r[0] for r in regions], regions


def median_period(starts):
    s = sorted(starts)
    if len(s) < 3:
        return None
    return float(np.median(np.diff(s)))


def near(x, xs, tol):
    return any(abs(x - y) <= tol for y in xs)


# ---- render a 3-against-4 poly mix, keeping the per-stream artifacts -------------------------
track = click_track(400, 6)  # 2400 ms
beats = [0, 400, 800, 1200, 1600, 2000]
streams = [{"ratio": 4}, {"ratio": 3}]
cfg = AutoMixerConfig(track, beats, sample_length=100, mode="poly", streams=streams)
combined, segs = PolyphonicAutoMixer().mix(cfg, return_streams=True)

if len(combined) == 0 or len(segs) != 2:
    failures.append("poly mix did not return a combined mix + 2 stream segments")
else:
    beat_period = 400.0
    sub = beat_period / 12.0  # LCM(3,4)=12 -> 33.3 ms

    (a_starts, a_regions), (b_starts, b_regions) = starts_of(segs[0]), starts_of(segs[1])
    print("stream A (ratio 4) starts:", a_starts)
    print("stream B (ratio 3) starts:", b_starts)

    # 1) Each stream fires at its own subdivision: A every beat/4 (=100 ms), B every beat/3 (=133 ms).
    pa, pb = median_period(a_starts), median_period(b_starts)
    print("measured period A=%s (expect ~100), B=%s (expect ~133)" % (pa, pb))
    if pa is None or abs(pa - 100) > 15:
        failures.append("stream A period %s != ~100 ms (beat/4)" % pa)
    if pb is None or abs(pb - 133.3) > 18:
        failures.append("stream B period %s != ~133 ms (beat/3)" % pb)

    # 2) The streams realign every 12 subdivisions (=400 ms): the times where BOTH fire are spaced
    #    ~400 ms apart — read from the stream onset timestamps, not by ear.
    coincidences = sorted(t for t in a_starts if near(t, b_starts, sub * 0.6))
    print("coincidences (both streams fire):", coincidences)
    cp = median_period(coincidences)
    print("coincidence period=%s (expect ~400 = 12 subdivisions)" % cp)
    if cp is None or abs(cp - 400) > 40:
        failures.append("streams do not realign every 12 subdivisions: coincidence period=%s" % cp)

    # 3) Genuinely LAYERED: there is a time where BOTH streams are non-silent at once (their
    #    non-silent regions overlap) — concatenation could never produce that. (Energy-summing is
    #    NOT a valid layering test: two random-phase grains can destructively interfere and lower
    #    the combined RMS; overlapping non-silent extent is the phase-independent proof.)
    overlap = any(a0 < b1 and b0 < a1 for a0, a1 in a_regions for b0, b1 in b_regions)
    if not overlap:
        failures.append("no time where both streams are non-silent — mix is concatenated, not layered")
    # The combined mix must actually contain the overlaid material at the crossings.
    if combined[0:90].dBFS == float("-inf"):
        failures.append("combined mix is silent at the t=0 crossing where both streams fire")

# ---- 5) Runs on hallucinated-grid hum and with default streams without erroring ---------------
hum = WhiteNoise().to_audio_segment(duration=1800).apply_gain(-25)
cfg_hum = AutoMixerConfig(hum, [], sample_length=120, mode="poly", streams=streams)
try:
    mix_hum = PolyphonicAutoMixer().mix(cfg_hum)
    if len(mix_hum) == 0 or mix_hum.dBFS == float("-inf"):
        failures.append("beatless hum produced an empty/silent poly mix")
except Exception as e:
    failures.append("poly mixer errored on beatless hum: %r" % e)

cfg_def = AutoMixerConfig(track, beats, sample_length=100, mode="poly")  # default streams
try:
    if len(PolyphonicAutoMixer().mix(cfg_def)) == 0:
        failures.append("poly mixer with default streams produced an empty mix")
except Exception as e:
    failures.append("poly mixer errored with default streams: %r" % e)

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("ok: 3-against-4 streams fire at beat/4 and beat/3, realign every 12 subdivisions, "
      "and are genuinely layered (overlapping non-silent streams)")
