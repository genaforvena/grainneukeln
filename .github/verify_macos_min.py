#!/usr/bin/env python3
"""Fail if any Mach-O in a bundle requires a macOS newer than TARGET.

Usage: verify_macos_min.py <bundle-dir> <target e.g. 10.13>

grainneukeln ships to a friend on macOS 10.13.6 (High Sierra). setup-python/pip pull *binary*
wheels whose embedded dylibs carry their own minimum-OS load command (LC_VERSION_MIN_MACOSX or
LC_BUILD_VERSION/minos); MACOSX_DEPLOYMENT_TARGET only governs what we compile from source, not
prebuilt wheels or the bundled ffmpeg. This gate reads the actual load command from every Mach-O
and refuses the build if even one needs newer than the target — turning "crashes on High Sierra"
into a red build that names the exact offending file, so we can pin an older wheel or ffmpeg.
"""
import pathlib
import re
import subprocess
import sys

MACHO_MAGIC = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",  # 64/32-bit little-endian
               b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",  # big-endian
               b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}  # fat / universal


LOAD_CMD = re.compile(r"^Load command \d+", re.M)
CMD_NAME = re.compile(r"^\s*cmd\s+(\S+)", re.M)
MINOS = re.compile(r"^\s*minos\s+(\d+)\.(\d+)", re.M)
VERSION = re.compile(r"^\s*version\s+(\d+)\.(\d+)", re.M)


def versions_in(out):
    r"""Minimum-OS versions in `otool -l` / `vtool -show-build` output.

    Parsed per LOAD COMMAND BLOCK, never by scanning the whole text for a number.
    `otool -l` is full of unrelated `version` lines -- every LC_LOAD_DYLIB carries
    a `current version` and a `compatibility version`, and those are dylib
    versions, not OS versions. A whole-text regex for `version (\d+)\.(\d+)`
    therefore returns things like 1022.1 and 907.0, and since the gate takes the
    MAXIMUM it then fails every build while looking like a strict check that found
    a real problem. It reported exactly that on the first bundle this gate ever
    saw -- the macOS job had never once run before 2026-08-21, so the parser's
    answer had never been read by anyone.

    The lesson is the one in the doctrine: when a probe returns a bare number,
    assert what QUESTION it answers. Two different load commands here answer
    "minimum macOS" (LC_BUILD_VERSION's `minos`, LC_VERSION_MIN_MACOSX's
    `version`) and a dozen answer something else in the same shape.
    """
    found = []
    for block in LOAD_CMD.split(out):
        name = CMD_NAME.search(block)
        if not name:
            continue
        if name.group(1) == "LC_BUILD_VERSION":
            # A fat/universal binary carries one block per arch; iOS-simulator and
            # macCatalyst blocks exist too, so require the MACOS platform when the
            # tool prints one.
            if "platform" in block and not re.search(r"^\s*platform\s+(MACOS|1)\b", block, re.M):
                continue
            m = MINOS.search(block)
            if m:
                found.append((int(m.group(1)), int(m.group(2))))
        elif name.group(1) == "LC_VERSION_MIN_MACOSX":
            m = VERSION.search(block)
            if m:
                found.append((int(m.group(1)), int(m.group(2))))
    return found


def min_macos(path):
    """Highest minimum-OS across all archs in the file, as (major, minor), or None."""
    for tool in (["otool", "-l", str(path)], ["vtool", "-show-build", str(path)]):
        try:
            out = subprocess.run(tool, capture_output=True, text=True).stdout
        except FileNotFoundError:
            continue
        versions = versions_in(out)
        if versions:
            return max(versions)
    return None


def main():
    bundle = pathlib.Path(sys.argv[1])
    tmaj, tmin = (int(x) for x in sys.argv[2].split("."))
    target = (tmaj, tmin)
    bad, checked = [], 0
    for f in bundle.rglob("*"):
        if not f.is_file() or f.is_symlink():
            continue
        try:
            if f.open("rb").read(4) not in MACHO_MAGIC:
                continue
        except OSError:
            continue
        checked += 1
        v = min_macos(f)
        if v and v > target:
            bad.append((f, v))
    if bad:
        print(f"FAIL: {len(bad)} component(s) require macOS newer than {tmaj}.{tmin}:")
        for f, v in sorted(bad, key=lambda x: x[1], reverse=True):
            print(f"  needs {v[0]}.{v[1]:<3} {f.relative_to(bundle)}")
        sys.exit(1)
    if checked == 0:
        # Zero Mach-O files is not a pass. It means the bundle path was wrong or
        # the magic-number sniff missed everything, and an empty check that prints
        # OK is the loudest failure mode this script has.
        print(f"FAIL: no Mach-O files found under {bundle} — nothing was checked.")
        sys.exit(1)
    print(f"OK: all {checked} Mach-O components support macOS {tmaj}.{tmin} or older.")


if __name__ == "__main__":
    main()
