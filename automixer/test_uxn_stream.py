"""Tests for the Uxn external control layer (Option A, genaforvena/grainneukeln#13).

RED-first: written before automixer/uxn_stream.py existed. Exercises the REAL vendored Uxn
toolchain (uxn_ctrl/build.sh + paramgen.rom) end-to-end -- no stub/mock ROM -- so a broken
build, a broken ROM, or a broken host parser all show up here, not just "the module imports".
"""
import os
import subprocess
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
UXN_CTRL = os.path.join(ROOT, "uxn_ctrl")
ASSET = os.path.join(ROOT, "assets", "test_audio.mp3")


def _ensure_uxn_toolchain():
    """Build the vendored uxnasm/uxncli if not already built (mirrors the mesh uxn-pilot: bin/
    is gitignored, source is vendored, every node/CI worker builds its own emulator)."""
    uxncli = os.path.join(UXN_CTRL, "bin", "uxncli")
    if not os.path.isfile(uxncli):
        subprocess.run(["./build.sh", "--rom"], cwd=UXN_CTRL, check=True,
                        capture_output=True, text=True)
    return uxncli


class UxnTickTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uxncli = _ensure_uxn_toolchain()
        cls.rom = os.path.join(UXN_CTRL, "paramgen.rom")

    def test_tick_output_is_a_valid_amc_fragment(self):
        from automixer.uxn_stream import uxn_tick
        line = uxn_tick(0, rom_path=self.rom, uxncli_path=self.uxncli)
        self.assertRegex(line, r"^l \d+ w \d+$")

    def test_tick_is_deterministic(self):
        from automixer.uxn_stream import uxn_tick
        a = uxn_tick(5, rom_path=self.rom, uxncli_path=self.uxncli)
        b = uxn_tick(5, rom_path=self.rom, uxncli_path=self.uxncli)
        self.assertEqual(a, b)

    def test_different_ticks_are_not_all_identical(self):
        # A real gate against the classic "silent fallback" trap: a ROM that always prints the
        # same line regardless of input would pass a naive smoke test. Assert real variation.
        from automixer.uxn_stream import uxn_tick
        lines = {uxn_tick(t, rom_path=self.rom, uxncli_path=self.uxncli) for t in range(8)}
        self.assertGreater(len(lines), 1, f"tick has no effect on output: {lines}")

    def test_l_value_stays_within_grainneukeln_contract(self):
        # mesh-sound-reflex's derive() clamps l to [120, 2000]ms -- the ROM's pool must too.
        from automixer.uxn_stream import uxn_tick
        for t in range(16):
            line = uxn_tick(t, rom_path=self.rom, uxncli_path=self.uxncli)
            l = int(line.split()[1])
            self.assertTrue(120 <= l <= 2000, f"tick {t}: l={l} outside [120,2000]: {line}")

    def test_missing_rom_raises_not_silent_default(self):
        from automixer.uxn_stream import uxn_tick
        with self.assertRaises(Exception):
            uxn_tick(0, rom_path="/nonexistent/paramgen.rom", uxncli_path=self.uxncli)


class RunUxnSequenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uxncli = _ensure_uxn_toolchain()
        cls.rom = os.path.join(UXN_CTRL, "paramgen.rom")

    def test_drives_n_renders_with_engine_untouched(self):
        # The engine (config_automix/automix) is exercised through its EXISTING public grammar --
        # Option A's whole promise. This is a real end-to-end render, truncated per the repo's own
        # O(n^2)-mixer test convention (see cutter/test_series_cli.py).
        from cutter.sample_cut_tool import SampleCutter
        from automixer.uxn_stream import run_uxn_sequence
        with tempfile.TemporaryDirectory() as d:
            cutter = SampleCutter(os.path.abspath(ASSET), d)
            cutter.audio = cutter.audio[:4000]
            cutter.beats = cutter.beats[cutter.beats < 4000]
            lines = run_uxn_sequence(cutter, 3, rom_path=self.rom, uxncli_path=self.uxncli)
            files = sorted(os.listdir(d))
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(files), 3)


if __name__ == "__main__":
    unittest.main()
