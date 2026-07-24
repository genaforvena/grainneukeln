"""Uxn ROM panel — resolution, readiness, and the dry-run preview.

The preview is the reason this panel exists: before it, the only way to learn what a ROM would do
(or that uxncli was never built) was to start N full grinds. These tests drive the REAL ROM through
the REAL emulator when it is built, and skip honestly when it is not — a preview test that passes
against a stub would assert nothing about the thing that breaks.
"""
import os
import tempfile
import unittest

from textual.widgets import Checkbox, Input, RichLog

from automixer.uxn_stream import DEFAULT_ROM, describe_line, preview_uxn_sequence
from tui.app import GrainTUI
from tui.state import SessionState
from tui.widgets.uxn_panel import UxnPanel


def _isolated_session():
    return os.path.join(tempfile.mkdtemp(), "session.json")


def _uxn_available():
    from automixer.uxn_stream import find_uxncli
    try:
        find_uxncli()
    except FileNotFoundError:
        return False
    return os.path.isfile(DEFAULT_ROM)


def _isolated_output():
    # Empty temp dir so tests never mount the operator's real 2.7 GB output/ corpus
    # (1000+ files → 5-12 s of widget-building per app instance). Hermetic + fast.
    return tempfile.mkdtemp()


class PreviewFunctionTest(unittest.TestCase):
    @unittest.skipUnless(_uxn_available(), "uxncli not built (uxn_ctrl/build.sh)")
    def test_preview_returns_one_line_per_tick_without_rendering(self):
        lines = preview_uxn_sequence(6)
        self.assertEqual(len(lines), 6)
        for line in lines:
            toks = describe_line(line)
            # every axis the ROM owns must be present — a ROM that emitted only `l` would still
            # produce "lines", so assert the CONTRACT, not the count.
            for axis in ("l", "w", "s", "c", "ss", "m"):
                self.assertIn(axis, toks, line)

    @unittest.skipUnless(_uxn_available(), "uxncli not built (uxn_ctrl/build.sh)")
    def test_preview_shows_the_mode_axis_moving(self):
        """The 2026-07-24 ROM addition: a run moves through cutting ALGORITHMS. The preview is
        worthless if it cannot show that, so gate it — 8 ticks at _MODE_PERIOD=4 spans two modes."""
        modes = [describe_line(l)["m"] for l in preview_uxn_sequence(8)]
        self.assertEqual(modes[:4], ["rw"] * 4)
        self.assertEqual(modes[4:], ["q"] * 4)

    def test_describe_line_parses_pairs(self):
        self.assertEqual(describe_line("l 200 w 4 m rw"), {"l": "200", "w": "4", "m": "rw"})
        self.assertEqual(describe_line(""), {})


class UxnPanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_blank_rom_resolves_to_the_vendored_default(self):
        app = GrainTUI(output_dir=_isolated_output(), session_path=_isolated_session())
        async with app.run_test() as pilot:
            panel = app.query_one(UxnPanel)
            self.assertEqual(panel.resolved_rom(), os.path.abspath(DEFAULT_ROM))
            app.query_one("#uxn_rom_path", Input).value = "/tmp/mine.rom"
            await pilot.pause()
            self.assertEqual(panel.resolved_rom(), "/tmp/mine.rom")

    async def test_missing_rom_is_reported_before_a_run_starts(self):
        app = GrainTUI(output_dir=_isolated_output(), session_path=_isolated_session())
        async with app.run_test() as pilot:
            app.query_one("#uxn_rom_path", Input).value = "/tmp/definitely-not-here.rom"
            await pilot.pause()
            ok, msg = app.query_one(UxnPanel).readiness()
            self.assertFalse(ok)
            self.assertIn("not found", msg)
            # and the state agrees — is_runnable must refuse, so the worker never spawns uxncli
            app.state.uxn_enabled = True
            app.state.cutter = object()
            app.state.sample_length_ms = 400
            runnable, reason = app.state.is_runnable()
            self.assertFalse(runnable)
            self.assertIn("ROM not found", reason)

    async def test_zero_ticks_refused(self):
        s = SessionState(cutter=object(), sample_length_ms=400, uxn_enabled=True, uxn_ticks=0)
        ok, reason = s.is_runnable()
        self.assertFalse(ok)
        self.assertIn("ticks", reason)

    async def test_toggles_write_through_to_state(self):
        app = GrainTUI(output_dir=_isolated_output(), session_path=_isolated_session())
        async with app.run_test() as pilot:
            app.query_one("#opt_uxn_enabled", Checkbox).value = True
            app.query_one("#opt_uxn_feedback", Checkbox).value = True
            app.query_one("#uxn_ticks", Input).value = "16"
            await pilot.pause()
            self.assertTrue(app.state.uxn_enabled)
            self.assertTrue(app.state.uxn_feedback)
            self.assertEqual(app.state.uxn_ticks, 16)

    @unittest.skipUnless(_uxn_available(), "uxncli not built (uxn_ctrl/build.sh)")
    async def test_preview_button_writes_the_plan_to_the_panel_log(self):
        app = GrainTUI(output_dir=_isolated_output(), session_path=_isolated_session())
        async with app.run_test() as pilot:
            app.query_one("#uxn_ticks", Input).value = "8"
            await pilot.pause()
            app.query_one(UxnPanel).preview()
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = "\n".join(str(l) for l in app.query_one("#uxn_log", RichLog).lines)
            self.assertIn("[ 0]", text)
            self.assertIn("← mode", text, "the tick where the ALGORITHM changes must be marked")
            self.assertIn("rw → q", text, "the plan summary must name the mode sequence")


class UxnPreseedLineTest(unittest.IsolatedAsyncioTestCase):
    async def test_preseed_carries_everything_the_rom_does_not_emit(self):
        """Mutation gate: the ROM owns l/w/s/c/ss/m, so seeding any of them would be overwritten on
        tick 0 and read as a lie. Everything else must be there."""
        app = GrainTUI(output_dir=_isolated_output(), session_path=_isolated_session())
        async with app.run_test() as pilot:
            s = app.state
            s.env_pct, s.reverse_prob = 12.0, 0.3
            s.euclid_k, s.euclid_n, s.lib_clusters = 5, 16, 9
            s.swing, s.fill_gain_db, s.snap, s.fill = 66.0, -9.0, True, False
            s.streams_spec, s.seed = "4;3", 1234
            line = app._uxn_preseed_line(s)
            for tok in ("env 12", "rv 0.3", "ek 5", "en 16", "lk 9", "sw 66", "fg -9",
                        "snap", "nofill", "pr 4;3", "seed 1234", "lib sim"):
                self.assertIn(tok, line)
            for owned in (" l ", " w ", " s ", " c ", " ss ", " m "):
                self.assertNotIn(owned, line, f"{owned!r} is ROM-owned — seeding it is a lie")


if __name__ == "__main__":
    unittest.main()
