"""External Uxn control layer (Option A, genaforvena/grainneukeln#13: "Integrate Uxn as a
programmable control/sequencing layer").

Uxn is a good fit for exactly one part of this: the deterministic, portable arithmetic that
decides WHICH pool entry a tick selects (its 8/16-bit integer stack, no floats, 64KB address
space). It is a bad fit for the automix engine itself -- the O(n^2) numpy mixer and librosa
beat detection need floating point and unbounded working memory a Uxn ROM cannot give them.

So Option A is implemented literally as its own "why this works" describes: the ROM runs in a
separate process (``uxn_ctrl/paramgen.rom``) and emits a stream of ``amc``-grammar parameter
lines (``l 500 w 4``); this module feeds each line straight into ``SampleCutter``'s EXISTING
``config_automix``/``automix`` methods -- the same entry points a human types at the REPL.
The audio engine is untouched.

The ROM sequences all 6 amc params (l/w/s/c/ss/m) and reads FOUR argv tokens, in this order: a
``feedback`` byte (0 = open-loop no-op for idx_c; ``--uxn-feedback`` measures a real one per tick
-- a per-tick regional rhythm_density scaled by the source's own adaptive ceiling, whose low 2
bits XOR-perturb the ``c``-band index), a ``tick`` whose 8-bit tick_lo byte drives l/w/s/c
(256-tick period), a coarser "macro tick" (``tick // 256``) whose low 2 bits pick ``ss``, and a
"mode tick" (``tick // _MODE_PERIOD``, default 4) whose low 2 bits pick the mixer MODE ``m``
(rw/q/poly/lib -- which algorithm cuts the grains). See uxn_ctrl/README.md.
"""
import os
import shutil
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROM = os.path.join(_HERE, "..", "uxn_ctrl", "paramgen.rom")
_VENDORED_UXNCLI = os.path.join(_HERE, "..", "uxn_ctrl", "bin", "uxncli")

# Mode changes every _MODE_PERIOD ticks. The mode is the whole cutting ALGORITHM (rw/q/poly/lib),
# so a per-tick flip would be chaos, not music; 4 lets each algorithm settle across a few renders
# before the ROM moves on. The macro-tick (ss) has its own coarser 256 period -- different params,
# different cadences, exactly like ss itself was added on its own token because tick_lo was spent.
_MODE_PERIOD = 4


def find_uxncli(uxncli_path=None):
    """Resolve the uxncli binary: explicit path, then the vendored build, then PATH."""
    if uxncli_path:
        return uxncli_path
    if os.path.isfile(_VENDORED_UXNCLI) and os.access(_VENDORED_UXNCLI, os.X_OK):
        return _VENDORED_UXNCLI
    found = shutil.which("uxncli")
    if found:
        return found
    raise FileNotFoundError(
        "uxncli not found -- run uxn_ctrl/build.sh to compile the vendored toolchain")


def uxn_tick(tick, feedback=0, rom_path=DEFAULT_ROM, uxncli_path=None):
    """Run the Uxn param-sequencer ROM for one tick; return its output line, e.g. 'l 500 w 4'.

    One subprocess per tick, matching the mesh's own uxn-pilot gates (lease-gate/band-gate):
    deterministic, byte-identical on any Uxn emulator/architecture, trivially testable. Raises
    on any failure to load/run the ROM -- empty output is a real failure, never a silent
    default (uxncli always exits 0 even when it fails to load a ROM, so the exit code itself
    is not a usable signal; non-empty stdout is the actual success predicate).

    Passes FOUR argv tokens, in this exact order: `feedback` (default 0, a true no-op --
    `x EOR 0 == x` -- so an unspecified feedback reproduces today's fully open-loop output byte
    for byte on every axis EXCEPT `m`, which is appended as a new sequenced axis in 2026-07-24;
    the feedback no-op is scoped to idx_c, which it is the only thing that touches), `tick`
    (its low byte drives l/w/s/c), ``tick // 256`` (its low 2 bits drive ss), and
    ``tick // _MODE_PERIOD`` (its low 2 bits drive the mixer MODE m). Feedback MUST come first:
    the ROM emits `c`'s string while processing the SECOND line it reads, so a feedback value
    arriving any later could never influence that selection (see uxn_ctrl/paramgen.tal's header
    comment and uxn_ctrl/README.md).
    """
    cli = find_uxncli(uxncli_path)
    result = subprocess.run(
        [cli, rom_path, str(int(feedback) & 0xFF), str(tick), str(tick // 256),
         str(tick // _MODE_PERIOD)],
        capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
    )
    line = result.stdout.strip()
    if not line:
        raise RuntimeError(
            f"uxncli produced no output for tick {tick} (feedback={feedback}, rom={rom_path}): "
            f"{result.stderr.strip()}"
        )
    return line


def preview_uxn_sequence(ticks, rom_path=DEFAULT_ROM, uxncli_path=None, cutter=None,
                         closed_loop=False):
    """Return the param lines the ROM WOULD emit for ticks 0..ticks-1 — without rendering anything.

    A ROM-driven run is N full grinds; before 2026-07-24 the only way to find out what a ROM would
    do (or that a hand-written ROM emits garbage, or that ``uxncli`` was never built) was to start
    those grinds and read the log as they went. Ticking the ROM is microseconds and touches no
    audio, so the sequence is knowable up front — this is that read.

    ``closed_loop`` requires a loaded ``cutter`` to measure the feedback byte from; without one it
    falls back to the open-loop byte (0) and the caller is expected to say so, rather than quietly
    presenting an open-loop preview as if it were the closed-loop plan.
    """
    lines = []
    for tick in range(max(0, int(ticks))):
        feedback = (_measure_feedback_byte(cutter, tick=tick)
                    if (closed_loop and cutter is not None) else 0)
        lines.append(uxn_tick(tick, feedback=feedback, rom_path=rom_path,
                              uxncli_path=uxncli_path))
    return lines


def describe_line(line):
    """Split one ROM param line into an ordered dict of amc token → value.

    Used by the TUI preview to show WHICH axis moved between ticks (the `m` mode axis especially —
    the 2026-07-24 addition that makes a run move through cutting ALGORITHMS, not just their knobs;
    reading that off a raw `l 200 w 4 s 0.5 c 0,0;1000,15000 ss 0.5 m rw` string is needless work).
    """
    toks = (line or "").split()
    out = {}
    i = 0
    while i + 1 < len(toks):
        out[toks[i]] = toks[i + 1]
        i += 2
    return out


def run_uxn_sequence(cutter, ticks, rom_path=DEFAULT_ROM, uxncli_path=None, closed_loop=False,
                     on_tick=None):
    """Drive `ticks` renders of `cutter` from the Uxn param stream.

    Each tick's line is handed to config_automix/automix exactly as a human-typed `amc ...`
    command would be -- the engine never knows the params came from a Uxn ROM instead of a
    keyboard. Returns the list of param lines actually applied, one per render.

    ``closed_loop=True`` computes a REAL feedback byte each tick from the source's measured
    character (a per-tick regional rhythm_density, scaled by the source's own adaptive ceiling
    -- see ``_measure_feedback_byte``), so the Uxn sequencer's `c`-band choice reacts to the
    part of the audio the run is currently working over instead of ticking through its table
    open-loop. Default `False` passes `feedback=0` every tick -- byte-for-byte the original
    open-loop behaviour (feedback is a true no-op for idx_c; the appended `m` axis is
    orthogonal and present in both modes).

    ``on_tick(index, line, phase)`` — optional progress callback, invoked TWICE per tick: once with
    ``phase="start"`` the moment the ROM's line is known (before the render), and once with
    ``phase="done"`` after that render lands. A single end-of-tick callback would leave the caller's
    progress bar frozen for the whole of the slowest thing in the loop (the grind), which is exactly
    the interval the operator most wants to see moving.
    """
    lines = []
    for tick in range(ticks):
        feedback = _measure_feedback_byte(cutter, tick=tick) if closed_loop else 0
        line = uxn_tick(tick, feedback=feedback, rom_path=rom_path, uxncli_path=uxncli_path)
        if on_tick:
            on_tick(tick, line, "start")
        cutter.config_automix("amc " + line)
        cutter.automix("am")
        lines.append(line)
        if on_tick:
            on_tick(tick, line, "done")
    return lines


_DENSITY_SAMPLE_MS = 2000
# Cap the profile at this many evenly-spaced grains. The full asset has hundreds of beat
# positions; measuring all of them is librosa-onset-heavy and stalls a test for minutes. 24 is
# enough headroom for per-tick regional variety across a 16-tick run (tick % len) while keeping a
# profile build to a handful of seconds -- and the cache means a multi-tick run pays it once.
_MAX_PROFILE_SAMPLES = 24
# Headroom above the source's OWN measured peak density. The fixed /5.0 ceiling saturated busy
# material to byte 255 (idx_c pinned at a constant XOR-by-3). Scaling against peak*headroom keeps
# the busiest region below 255 while still spreading quiet-vs-busy across the byte range. >1.0
# guarantees local_density/ceiling < 1 even when local IS the peak, so the byte can never pin.
_FEEDBACK_HEADROOM = 1.25


def _density_profile(cutter, sample_len=_DENSITY_SAMPLE_MS):
    """Lazily build + cache the source's rhythm-density profile on the cutter, keyed by sample
    window. Returns ``(positions, densities)`` -- parallel lists of (capped, evenly-spaced)
    beat-grid grain offsets and their measured onset densities. Built ONCE per cutter (the
    source does not change mid-run), so a multi-tick closed-loop run pays the measure cost once,
    not once per tick."""
    cached = getattr(cutter, "_uxn_density_profile", None)
    if cached is not None and cached[0] == sample_len:
        return cached[1], cached[2]
    from automixer.features import measure_grain

    audio = getattr(cutter, "audio", None)
    beats = getattr(cutter, "beats", None)
    if audio is None or beats is None or len(audio) == 0:
        cutter._uxn_density_profile = (sample_len, [], [])
        return [], []
    positions = sorted(set(int(b) for b in beats if 0 <= b <= len(audio) - sample_len))
    if not positions:
        cutter._uxn_density_profile = (sample_len, [], [])
        return [], []
    if len(positions) > _MAX_PROFILE_SAMPLES:
        step = len(positions) / _MAX_PROFILE_SAMPLES
        positions = [positions[int(i * step)] for i in range(_MAX_PROFILE_SAMPLES)]
    densities = [measure_grain(audio[p:p + sample_len])["rhythm_density"] for p in positions]
    cutter._uxn_density_profile = (sample_len, positions, densities)
    return positions, densities


def _measure_feedback_byte(cutter, tick=0, sample_len=_DENSITY_SAMPLE_MS):
    """A coarse, audio-reactive feedback byte for closed-loop Uxn control -- only its low 2 bits
    reach the ROM (``idx_c = ((tick>>6)&3) EOR (byte&3)``), so it is a perturbation key, not a
    precision control signal.

    Two fixes over the original whole-source-average (2026-07-24):

    1. ADAPTIVE CEILING. The original divided by a fixed 5.0 onsets/sec; uniformly busy material
       saturated to byte 255 and pinned idx_c at a constant XOR-by-3. We now scale against the
       source's OWN peak density times headroom (``_FEEDBACK_HEADROOM``), so even the busiest
       region stays below 255 -- different busy-ness levels map to different perturbations
       instead of all collapsing to one. Headroom > 1 structurally guarantees the byte < 255.

    2. PER-TICK REGIONAL MEASUREMENT. The original averaged the WHOLE source every tick -- the
       same byte every call, i.e. a constant per-run idx_c offset, not a closed loop. We now
       measure the region at ``positions[tick % len(positions)]`` each tick, advancing through the
       source, so a varied song yields different bytes (and thus a moving idx_c) across the run.
       A genuinely uniform source still yields a near-constant byte -- which is honest: nothing
       varies for the loop to react to.

    Uses the one existing measure tract (``automixer.features.measure_grain`` -- no new analyzer)
    and the 2000ms grain window fixed in the 2026-07-21 review (300ms extrapolated a single onset
    past the per-second ceiling). See ``automixer/test_uxn_stream.py::MeasureFeedbackByteTest``."""
    positions, densities = _density_profile(cutter, sample_len)
    if not densities:
        return 0
    peak = max(densities)
    ceiling = max(peak * _FEEDBACK_HEADROOM, 1.0)
    idx = tick % len(positions)
    local = densities[idx]
    scaled = int(min(1.0, local / ceiling) * 255)
    return max(0, min(255, scaled))
