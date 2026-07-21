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

The ROM sequences all 5 amc params (l/w/s/c/ss) and reads THREE argv tokens, in this order: a
``feedback`` byte (0 = open-loop no-op; ``--uxn-feedback`` measures a real one per tick and its
low 2 bits XOR-perturb the ``c``-band index), a ``tick`` whose 8-bit tick_lo byte drives l/w/s/c
(256-tick period), and a coarser "macro tick" (``tick // 256``) whose low 2 bits pick ``ss``'s
pool entry. Net period 1024 ticks before the whole sequence repeats. See uxn_ctrl/README.md.
"""
import os
import shutil
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROM = os.path.join(_HERE, "..", "uxn_ctrl", "paramgen.rom")
_VENDORED_UXNCLI = os.path.join(_HERE, "..", "uxn_ctrl", "bin", "uxncli")


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

    Passes THREE argv tokens, in this exact order: `feedback` (default 0, a true no-op --
    `x EOR 0 == x` -- so an unspecified feedback reproduces today's fully open-loop output byte
    for byte), `tick` (its low byte drives l/w/s/c), and `tick // 256` (its low 2 bits drive ss).
    Feedback MUST come first: the ROM emits `c`'s string while processing the SECOND line it
    reads, so a feedback value arriving any later could never influence that selection (see
    uxn_ctrl/paramgen.tal's header comment and uxn_ctrl/README.md).
    """
    cli = find_uxncli(uxncli_path)
    result = subprocess.run(
        [cli, rom_path, str(int(feedback) & 0xFF), str(tick), str(tick // 256)],
        capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
    )
    line = result.stdout.strip()
    if not line:
        raise RuntimeError(
            f"uxncli produced no output for tick {tick} (feedback={feedback}, rom={rom_path}): "
            f"{result.stderr.strip()}"
        )
    return line


def run_uxn_sequence(cutter, ticks, rom_path=DEFAULT_ROM, uxncli_path=None, closed_loop=False):
    """Drive `ticks` renders of `cutter` from the Uxn param stream.

    Each tick's line is handed to config_automix/automix exactly as a human-typed `amc ...`
    command would be -- the engine never knows the params came from a Uxn ROM instead of a
    keyboard. Returns the list of param lines actually applied, one per render.

    ``closed_loop=True`` computes a REAL feedback byte each tick from the current source's
    measured character (a handful of evenly-spaced beat-grid grains, average rhythm_density
    scaled to 0-255 -- see ``_measure_feedback_byte``), so the Uxn sequencer's `c`-band choice
    reacts to the actual audio instead of ticking through its table open-loop. Default `False`
    passes `feedback=0` every tick -- byte-for-byte the original open-loop behaviour.
    """
    lines = []
    for tick in range(ticks):
        feedback = _measure_feedback_byte(cutter) if closed_loop else 0
        line = uxn_tick(tick, feedback=feedback, rom_path=rom_path, uxncli_path=uxncli_path)
        cutter.config_automix("amc " + line)
        cutter.automix("am")
        lines.append(line)
    return lines


def _measure_feedback_byte(cutter):
    """A cheap, coarse feedback byte for closed-loop Uxn control: sample a handful of evenly-
    spaced beat-grid grains from the CURRENT source, measure via the one existing measure tract
    (``automixer.features.measure_grain`` -- no new analyzer), average onset density (a real,
    audible axis: how busy the material is), clamp/scale a fixed practical range (0-5 onsets/sec
    covers real material -- see automixer/features.py's own rhythm_density docs) to a byte. Only
    the low 2 bits of the returned byte are actually consumed by the ROM (idx_c is 2 bits), so
    this need not be a precision measurement -- it is a coarse perturbation key, not a control
    signal in its own right.

    Review finding (2026-07-21): a 300ms grain window made this saturate to a CONSTANT on real
    audio -- rhythm_density is onsets extrapolated to a per-second rate, and even a single onset
    in a 300ms window already extrapolates past the assumed 0-5/sec ceiling (measured: real
    300ms grains from assets/test_audio.mp3 ranged ~3.3-13.3, sampled at 0/30/60/90/120s all
    landed >=5 -> byte 255 every time, low 2 bits pinned at 3). A LONGER grain window fixes this
    at the source rather than re-guessing another ceiling: measured with sample_len=2000ms, the
    SAME song's 8-pick average lands at ~3.3-5.9 onsets/sec across different regions -- squarely
    inside the original 0-5 assumption, which was correct for a per-SECOND rate, just violated by
    a window an order of magnitude shorter than a second. See
    automixer/test_uxn_stream.py::MeasureFeedbackByteTest for the real-region regression gate."""
    from automixer.features import measure_grain

    audio = getattr(cutter, "audio", None)
    beats = getattr(cutter, "beats", None)
    if audio is None or beats is None or len(beats) == 0 or len(audio) == 0:
        return 0
    sample_len = 2000
    positions = sorted(set(int(b) for b in beats if 0 <= b <= len(audio) - sample_len))
    if not positions:
        return 0
    step = max(1, len(positions) // 8)
    picks = positions[::step][:8]
    densities = [measure_grain(audio[p:p + sample_len])["rhythm_density"] for p in picks]
    avg = sum(densities) / len(densities) if densities else 0.0
    scaled = int(min(1.0, avg / 5.0) * 255)
    return max(0, min(255, scaled))
