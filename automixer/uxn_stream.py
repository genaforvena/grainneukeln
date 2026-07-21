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

Scope note: the current ROM only sequences ``l`` (grain length) and ``w`` (window divider),
both natively integer params. ``s``/``ss`` (float speed ratios) and ``c`` (frequency bands)
would need a fixed-point or string-pool extension to the ROM -- straightforward given the same
table-lookup pattern, just not built yet (see uxn_ctrl/README.md).
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


def uxn_tick(tick, rom_path=DEFAULT_ROM, uxncli_path=None):
    """Run the Uxn param-sequencer ROM for one tick; return its output line, e.g. 'l 500 w 4'.

    One subprocess per tick, matching the mesh's own uxn-pilot gates (lease-gate/band-gate):
    deterministic, byte-identical on any Uxn emulator/architecture, trivially testable. Raises
    on any failure to load/run the ROM -- empty output is a real failure, never a silent
    default (uxncli always exits 0 even when it fails to load a ROM, so the exit code itself
    is not a usable signal; non-empty stdout is the actual success predicate).
    """
    cli = find_uxncli(uxncli_path)
    result = subprocess.run(
        [cli, rom_path, str(tick)],
        capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
    )
    line = result.stdout.strip()
    if not line:
        raise RuntimeError(
            f"uxncli produced no output for tick {tick} (rom={rom_path}): "
            f"{result.stderr.strip()}"
        )
    return line


def run_uxn_sequence(cutter, ticks, rom_path=DEFAULT_ROM, uxncli_path=None):
    """Drive `ticks` renders of `cutter` from the Uxn param stream.

    Each tick's line is handed to config_automix/automix exactly as a human-typed `amc ...`
    command would be -- the engine never knows the params came from a Uxn ROM instead of a
    keyboard. Returns the list of param lines actually applied, one per render.
    """
    lines = []
    for tick in range(ticks):
        line = uxn_tick(tick, rom_path=rom_path, uxncli_path=uxncli_path)
        cutter.config_automix("amc " + line)
        cutter.automix("am")
        lines.append(line)
    return lines
