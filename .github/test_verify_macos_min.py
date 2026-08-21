"""The parser, against real `otool -l` shapes. No macOS needed.

This gate had never run: every release's macOS job queued on a dead runner label
for 24h and was cancelled, so the first time its output was read was 2026-08-21,
and it was wrong. It scanned the whole of `otool -l` for `version N.M` and took
the maximum, which is a dylib's `current version` — 1022.1, 907.0 — never an OS.
A gate you have not seen pass on a real input is not a gate either.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_macos_min import versions_in  # noqa: E402

# Trimmed from real output: an LC_BUILD_VERSION saying 10.13, surrounded by the
# dylib version numbers that used to be mistaken for it.
OTOOL_BUILD_VERSION = """\
Load command 8
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform MACOS
    minos 10.13
      sdk 10.15
   ntools 1
Load command 9
          cmd LC_ID_DYLIB
      cmdsize 56
         name @rpath/libx.dylib (offset 24)
   current version 907.0.0
compatibility version 1.0.0
Load command 10
          cmd LC_LOAD_DYLIB
      cmdsize 56
         name /usr/lib/libSystem.B.dylib (offset 24)
   current version 1022.1.0
compatibility version 1.0.0
Load command 11
      cmd LC_SOURCE_VERSION
  cmdsize 16
  version 60.1
"""

OTOOL_VERSION_MIN = """\
Load command 6
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 10.9
      sdk 10.13
Load command 7
          cmd LC_LOAD_DYLIB
      cmdsize 56
   current version 1319.0.0
compatibility version 1.0.0
"""

OTOOL_TOO_NEW = OTOOL_BUILD_VERSION.replace("minos 10.13", "minos 12.0")

FAT_TWO_ARCHS = OTOOL_BUILD_VERSION + OTOOL_BUILD_VERSION.replace("minos 10.13", "minos 11.0")

IOS_SIMULATOR_BLOCK = """\
Load command 8
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform IOSSIMULATOR
    minos 17.0
      sdk 17.0
   ntools 1
"""


def test_a_dylib_current_version_is_not_an_os_version():
    assert versions_in(OTOOL_BUILD_VERSION) == [(10, 13)], \
        "907.0 / 1022.1 / 60.1 are dylib and source versions, not minimum-OS"


def test_the_older_load_command_is_read_from_its_own_block():
    assert versions_in(OTOOL_VERSION_MIN) == [(10, 9)]


def test_a_genuinely_too_new_bundle_is_still_caught():
    assert max(versions_in(OTOOL_TOO_NEW)) == (12, 0)


def test_a_fat_binary_reports_every_arch():
    assert max(versions_in(FAT_TWO_ARCHS)) == (11, 0)


def test_a_non_macos_platform_block_is_ignored():
    assert versions_in(IOS_SIMULATOR_BLOCK) == [], \
        "an iOS-simulator minos is not a claim about macOS"


def test_no_load_commands_means_no_answer_not_a_zero():
    assert versions_in("") == []
