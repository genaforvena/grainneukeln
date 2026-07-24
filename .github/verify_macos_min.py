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


def min_macos(path):
    """Highest minimum-OS across all archs in the file, as (major, minor), or None."""
    versions = []
    for tool in (["vtool", "-show-build", str(path)], ["otool", "-l", str(path)]):
        try:
            out = subprocess.run(tool, capture_output=True, text=True).stdout
        except FileNotFoundError:
            continue
        # vtool: "minos 10.13"; otool LC_BUILD_VERSION: "minos 10.13";
        # otool LC_VERSION_MIN_MACOSX: "version 10.13"
        for m in re.finditer(r"\b(?:minos|version)\s+(\d+)\.(\d+)", out):
            versions.append((int(m.group(1)), int(m.group(2))))
        if versions:
            break
    return max(versions) if versions else None


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
    print(f"OK: all {checked} Mach-O components support macOS {tmaj}.{tmin} or older.")


if __name__ == "__main__":
    main()
