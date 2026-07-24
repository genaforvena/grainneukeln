"""Cyclic pattern engine — `pat` / `cyc` / `rot` / `acc` (2026-07-24).

Zero-dep on purpose — this repo has no test runner. Run it directly:

    PYTHONPATH=. .venv/bin/python tests/test_patterns.py

Two halves:

1. **Parser gates** (pure): the grammar — named timeline, `x..x` / `1001` string, `+3,3,2`
   additive meter, rotation, accent maps. These assert the resolved data, which IS the parser's
   whole output.
2. **Artifact gates** (rendered): the pattern has to be *audible in the bytes*. Every gate below
   renders a mix on a 400 ms click track and reads grain starts back with
   ``pydub.detect_nonsilent`` — never from a log the mixer could forge. A `cyc` that is ignored,
   an `acc` that never reaches the grain, a `rot` that rotates the parse but not the grid all
   look identical to a passing parser test and are caught only here.
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pydub import AudioSegment
from pydub.generators import Sine
from pydub.silence import detect_nonsilent

from automixer.config import AutoMixerConfig
from automixer.mixers.quantized_mixer import QuantizedAutoMixer
from automixer.iterators.patterns import (
    NAMED_PATTERNS, parse_pattern, parse_accents, rotate, additive, resolve_pattern,
    PatternError,
)

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


def click_track(period_ms=400, n_clicks=6):
    click = Sine(1000).to_audio_segment(duration=5).apply_gain(-1)
    rest = AudioSegment.silent(duration=period_ms - 5)
    track = AudioSegment.silent(duration=0)
    for _ in range(n_clicks):
        track += click + rest
    return track


def grain_starts(mix, silence_thresh=-40, min_silence_len=20):
    regions = detect_nonsilent(mix, min_silence_len=min_silence_len,
                               silence_thresh=silence_thresh, seek_step=1)
    return [start for start, _end in regions]


print("== 1. parse_pattern grammar ==")

check("x-dot string", parse_pattern("x..x..x.") == [1, 0, 0, 1, 0, 0, 1, 0])
check("binary string", parse_pattern("10010010") == [1, 0, 0, 1, 0, 0, 1, 0])
check("dash rest", parse_pattern("x--x--x-") == [1, 0, 0, 1, 0, 0, 1, 0])
check("whitespace/bar separators ignored",
      parse_pattern("x..x | ..x.") == [1, 0, 0, 1, 0, 0, 1, 0])
check("additive +3,3,2", parse_pattern("+3,3,2") == [1, 0, 0, 1, 0, 0, 1, 0])
check("additive helper", additive([2, 2, 2, 3]) == [1, 0, 1, 0, 1, 0, 1, 0, 0])
check("named tresillo resolves", parse_pattern("tresillo") == [1, 0, 0, 1, 0, 0, 1, 0])
check("named is case-insensitive", parse_pattern("TRESILLO") == parse_pattern("tresillo"))

try:
    parse_pattern("zzz")
    check("unknown name raises", False, "no PatternError")
except PatternError:
    check("unknown name raises", True)

try:
    parse_pattern("........")
    check("all-rest pattern raises", False, "no PatternError")
except PatternError:
    check("all-rest pattern raises", True)


print("== 2. the named library is well-formed ==")

bad = []
for nm, entry in NAMED_PATTERNS.items():
    pat = parse_pattern(entry["pat"])
    if not any(pat):
        bad.append(f"{nm}: no hits")
    if entry.get("cyc", 1) <= 0:
        bad.append(f"{nm}: cyc<=0")
    acc = entry.get("acc")
    if acc is not None and len(parse_accents(acc)) not in (len(pat), 1):
        # an accent map may be shorter (cycled) but must divide the pattern evenly
        if len(pat) % len(parse_accents(acc)) != 0:
            bad.append(f"{nm}: accent map {len(parse_accents(acc))} does not divide {len(pat)}")
check("every named entry parses + has hits", not bad, str(bad))
check("library is non-trivial", len(NAMED_PATTERNS) >= 15, f"n={len(NAMED_PATTERNS)}")
check("bembe is the 7-stroke standard bell",
      parse_pattern("bembe") == [1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0])
check("son clave 3-2 hits 0,3,6,10,12",
      [i for i, v in enumerate(parse_pattern("clave32")) if v] == [0, 3, 6, 10, 12])
check("teental is all-hit with a khali accent",
      all(parse_pattern("teental")) and len(parse_pattern("teental")) == 16)


print("== 3. rotate / accents ==")

check("rotate left by 1", rotate([1, 0, 0, 1], 1) == [0, 0, 1, 1])
check("rotate by 0 is identity", rotate([1, 0, 0, 1], 0) == [1, 0, 0, 1])
check("rotate wraps past length", rotate([1, 0, 0, 1], 5) == rotate([1, 0, 0, 1], 1))
check("negative rotate goes right", rotate([1, 0, 0, 1], -1) == [1, 1, 0, 0])
check("accent dB list", parse_accents("0,-6,-3") == [0.0, -6.0, -3.0])
check("accent list tolerates spaces", parse_accents(" 0 , -6 ") == [0.0, -6.0])


print("== 4. resolve_pattern — the one call site both CLI and TUI use ==")

pat, cyc, acc = resolve_pattern("bembe")
check("named default cycle comes from the library", cyc == 4.0, f"cyc={cyc}")
check("named default accents come from the library", acc is not None and len(acc) == len(pat))

pat, cyc, acc = resolve_pattern("bembe", cyc=2, acc="0,-9")
check("explicit cyc overrides the library default", cyc == 2.0)
# A short map is cycled UP to the pattern length at resolve time (not lazily at lookup) so a
# later `rot` rotates map and pattern together instead of shearing them apart.
check("explicit acc overrides the library default", acc == [0.0, -9.0] * 6, str(acc))

pat_r, _, acc_r = resolve_pattern("bembe", rot=2)
pat_0, _, acc_0 = resolve_pattern("bembe")
check("rot rotates the pattern", pat_r == rotate(pat_0, 2))
check("rot rotates the accents WITH the pattern", acc_r == rotate(acc_0, 2),
      "an accent map left behind by a rotation lands the sam on the wrong stroke")

pat, cyc, acc = resolve_pattern("+2,2,2,3")
check("additive spec resolves without a name", pat == [1, 0, 1, 0, 1, 0, 1, 0, 0])
check("bare spec defaults to cyc=1", cyc == 1.0)
check("bare spec has no accents", acc is None)


print("== 5. ARTIFACT: the pattern is audible on the grid ==")

# 400 ms beat. `pat tresillo` with cyc 1 must reproduce exactly what `ek 3 en 8` renders:
# the new engine is a superset, not a different grid.
track = click_track(400, 6)
beats = [0, 400, 800, 1200, 1600, 2000]

cfg_e = AutoMixerConfig(track, beats, sample_length=100, mode="q",
                        euclid_k=3, euclid_n=8, seed=7, fill=False)
starts_e = grain_starts(QuantizedAutoMixer().mix(cfg_e))
cfg_p = AutoMixerConfig(track, beats, sample_length=100, mode="q",
                        pattern=parse_pattern("tresillo"), cycle_beats=1.0, seed=7, fill=False)
starts_p = grain_starts(QuantizedAutoMixer().mix(cfg_p))
check("pat tresillo == ek 3 en 8 (same grid)", starts_e == starts_p,
      f"euclid={starts_e[:6]} pat={starts_p[:6]}")

# cyc 4: a 16-slot clave spread over FOUR beats -> slot = 1600/16 = 100 ms, hits at
# 0,300,600,1000,1200 then +1600. With cyc 1 the same pattern would be crammed into one beat
# (slot 25 ms) -- a blur, and the bug this parameter exists to fix.
cfg_c = AutoMixerConfig(track, beats, sample_length=100, mode="q",
                        pattern=parse_pattern("clave32"), cycle_beats=4.0, seed=7, fill=False)
starts_c = grain_starts(QuantizedAutoMixer().mix(cfg_c))
expected = [0, 300, 600, 1000, 1200, 1600, 1900, 2200]
hit = sum(1 for e in expected if any(abs(e - s) <= 12 for s in starts_c))
check("cyc 4 spreads a 16-slot clave over 4 beats", hit >= 6,
      f"matched {hit}/{len(expected)} of {expected} in {starts_c[:10]}")

# ...and cyc must actually CHANGE the grid, or the gate above passes on a hardcoded default.
cfg_c1 = AutoMixerConfig(track, beats, sample_length=100, mode="q",
                         pattern=parse_pattern("clave32"), cycle_beats=1.0, seed=7, fill=False)
starts_c1 = grain_starts(QuantizedAutoMixer().mix(cfg_c1))
check("cyc 1 vs cyc 4 render different grids", starts_c != starts_c1,
      "cycle_beats is being ignored")

# rot: rotating the pattern moves the grid, and by the amount the rotation implies.
cfg_r = AutoMixerConfig(track, beats, sample_length=100, mode="q",
                        pattern=rotate(parse_pattern("tresillo"), 3), cycle_beats=1.0,
                        seed=7, fill=False)
starts_r = grain_starts(QuantizedAutoMixer().mix(cfg_r))
check("rot moves the grid", starts_r != starts_p, "rotation had no audible effect")

print("== 6. ARTIFACT: accents reach the rendered bytes ==")

# An all-hit 4-slot pattern; slot 1 driven 24 dB down must come back QUIETER in the render than
# slot 0. Read from the audio, per slot, not from the config.
pat4 = [1, 1, 1, 1]
loud = AutoMixerConfig(track, beats, sample_length=100, mode="q",
                       pattern=pat4, cycle_beats=1.0, seed=11, fill=False)
mix_loud = QuantizedAutoMixer().mix(loud)
quiet = AutoMixerConfig(track, beats, sample_length=100, mode="q",
                        pattern=pat4, cycle_beats=1.0, seed=11, fill=False,
                        accents=[0.0, -24.0, 0.0, 0.0])
mix_quiet = QuantizedAutoMixer().mix(quiet)

slot = 100.0  # 400 ms beat / 4 slots


def slot_dbfs(mix, idx):
    a = int(idx * slot)
    seg = mix[a:a + int(slot)]
    return seg.dBFS


d_loud = slot_dbfs(mix_loud, 1)
d_quiet = slot_dbfs(mix_quiet, 1)
check("accented-down slot is quieter in the RENDER", d_quiet < d_loud - 10,
      f"slot1 {d_loud:.1f} dBFS -> {d_quiet:.1f} dBFS")
check("un-accented slot is untouched",
      abs(slot_dbfs(mix_quiet, 2) - slot_dbfs(mix_loud, 2)) < 0.5,
      f"slot2 moved {slot_dbfs(mix_loud, 2):.2f} -> {slot_dbfs(mix_quiet, 2):.2f}")

print("== 7. back-compat: no pattern params == today's euclidean behaviour ==")
cfg_a = AutoMixerConfig(track, beats, sample_length=100, mode="q", euclid_k=5, euclid_n=8, seed=3)
cfg_b = AutoMixerConfig(track, beats, sample_length=100, mode="q", euclid_k=5, euclid_n=8, seed=3)
check("unchanged config still renders byte-identically under a seed",
      QuantizedAutoMixer().mix(cfg_a).raw_data == QuantizedAutoMixer().mix(cfg_b).raw_data)

print("== 8. the timeline sweep: `pat` is series-expandable ==")
from automixer.series import expand_amc_series, SeriesError

combos = [" ".join(c) for c in expand_amc_series("amc m q pat [bembe,clave32,+2;2;3]".split())]
check("pat sweeps into one render per timeline",
      combos == ["amc m q pat bembe", "amc m q pat clave32", "amc m q pat +2;2;3"], str(combos))
check("rot sweeps", len(expand_amc_series("amc m q pat bembe rot [0,3,6]".split())) == 3)
try:
    expand_amc_series("amc m q acc [0,-9]".split())
    check("acc series is REJECTED, not silently rendered once", False, "expanded")
except SeriesError:
    # An accent map is itself a comma list, so the series splitter would shred it. The old
    # behaviour was to pass the literal "[0,-9]" through to the amc parser — one render, no
    # message. A key the parser reads must fail loudly instead.
    check("acc series is REJECTED, not silently rendered once", True)
check("a typo'd key still passes through (unchanged contract)",
      len(expand_amc_series("amc z [1,2,3]".split())) == 1)

print("== 9. a REJECTED config does not render ==")
# Before the pattern engine, every `amc` error path printed a message and returned — and the CLI
# driver rendered anyway, on the PREVIOUS config, saving it under a filename naming that config.
# So `amc m q pat clavee` (typo) came back as a plausible euclidean render with nothing to say the
# timeline never arrived: the silent-fallback trap, one layer up from the mixer. config_automix now
# reports whether it APPLIED anything and the drivers gate the render on it.
import tempfile
from cutter.sample_cut_tool import SampleCutter

with tempfile.TemporaryDirectory() as td:
    src = os.path.join(td, "click.wav")
    click_track(400, 6).export(src, format="wav")
    cutter = SampleCutter(src, td)
    check("a good pattern applies (True)", cutter.config_automix("amc m q pat bembe") is True)
    check("an unknown pattern is rejected (False)",
          cutter.config_automix("amc m q pat clavee") is False)
    check("a bad accent map is rejected (False)",
          cutter.config_automix("amc m q pat bembe acc loud") is False)
    check("`pat list` is informational, not a config (False)",
          cutter.config_automix("amc m q pat list") is False)
    check("a rejected config leaves the PREVIOUS pattern in place",
          cutter.auto_mixer_config.pattern == parse_pattern("bembe"))

print()
if failures:
    print(f"FAILED {len(failures)}: {failures}")
    sys.exit(1)
print("all pattern gates pass")
