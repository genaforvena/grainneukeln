import unittest
from textual.app import App, ComposeResult
from textual.widgets import Checkbox, Input, Select
from tui.state import SessionState
from tui.widgets.mode_panel import ModePanel


class _Host(App):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        yield ModePanel(self._state)


class ModePanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_valid_values_write_back(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test():
            panel = app.query_one(ModePanel)
            panel.query_one("#mode", Select).value = "q"
            panel.query_one("#euclid_k", Input).value = "5"
            panel.query_one("#euclid_n", Input).value = "13"
            panel.query_one("#swing", Input).value = "66"
            panel.query_one("#fill_gain_db", Input).value = "-3"
            panel.query_one("#lib_policy", Select).value = "contrast"
            panel.query_one("#lib_clusters", Input).value = "8"
            panel.query_one("#streams_spec", Input).value = "4:1-2000;3:6000-15000"
            panel.query_one("#snap", Checkbox).value = True
            panel.query_one("#fill", Checkbox).value = False
            errs = panel.apply_to_state()
            self.assertEqual(errs, [])
            self.assertEqual(state.mode, "q")
            self.assertEqual((state.euclid_k, state.euclid_n), (5, 13))
            self.assertEqual(state.swing, 66.0)
            self.assertEqual(state.fill_gain_db, -3.0)
            self.assertEqual(state.lib_policy, "contrast")
            self.assertEqual(state.lib_clusters, 8)
            self.assertEqual(state.streams_spec, "4:1-2000;3:6000-15000")
            self.assertTrue(state.snap)
            self.assertFalse(state.fill)

    async def test_euclid_k_gt_n_reported_not_written(self):
        state = SessionState()   # defaults euclid_k=3, euclid_n=8
        app = _Host(state)
        async with app.run_test():
            panel = app.query_one(ModePanel)
            panel.query_one("#euclid_k", Input).value = "9"
            panel.query_one("#euclid_n", Input).value = "8"
            errs = panel.apply_to_state()
            self.assertTrue(any("Euclid" in e for e in errs))
            self.assertEqual(state.euclid_k, 3)   # unchanged
            self.assertEqual(state.euclid_n, 8)

    async def test_bad_streams_spec_reported_not_written(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test():
            panel = app.query_one(ModePanel)
            panel.query_one("#streams_spec", Input).value = "notaratio:bad"
            errs = panel.apply_to_state()
            self.assertTrue(any("Poly streams" in e for e in errs))
            self.assertEqual(state.streams_spec, "")   # unchanged

    async def test_out_of_range_and_nonnumeric_reported(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test():
            panel = app.query_one(ModePanel)
            panel.query_one("#swing", Input).value = "999"     # > 100
            panel.query_one("#lib_clusters", Input).value = "x"
            errs = panel.apply_to_state()
            self.assertTrue(any("Swing" in e for e in errs))
            self.assertTrue(any("Lib clusters" in e for e in errs))
            self.assertEqual(state.swing, 0.0)                 # unchanged


class ModePanelPatternTest(unittest.IsolatedAsyncioTestCase):
    """The four pattern knobs are reachable from the panel, not only from the amc bar — the parity
    claim is about the TUI, and a knob that exists only in the command bar is half-wired."""

    async def test_pattern_fields_write_back(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test():
            panel = app.query_one(ModePanel)
            panel.query_one("#pattern_spec", Input).value = "bembe"
            panel.query_one("#cycle_beats", Input).value = "4"
            panel.query_one("#pattern_rot", Input).value = "2"
            panel.query_one("#accents_spec", Input).value = "0,-9,-5"
            errs = panel.apply_to_state()
            self.assertEqual(errs, [])
            self.assertEqual(state.pattern_spec, "bembe")
            self.assertEqual(state.cycle_beats, 4.0)
            self.assertEqual(state.pattern_rot, 2)
            self.assertEqual(state.accents_spec, "0,-9,-5")

    async def test_blank_pattern_fields_are_the_default_not_an_error(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test():
            errs = app.query_one(ModePanel).apply_to_state()
            self.assertEqual(errs, [])
            self.assertEqual(state.pattern_spec, "")
            self.assertIsNone(state.cycle_beats)
            self.assertEqual(state.pattern_rot, 0)

    async def test_unknown_pattern_reported_not_written(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test():
            panel = app.query_one(ModePanel)
            panel.query_one("#pattern_spec", Input).value = "notapattern"
            errs = panel.apply_to_state()
            self.assertTrue(any("Pattern" in e for e in errs), errs)
            self.assertEqual(state.pattern_spec, "")   # unchanged — no silent euclid fallback

    async def test_bad_accent_map_reported_not_written(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test():
            panel = app.query_one(ModePanel)
            panel.query_one("#accents_spec", Input).value = "0,notadb"
            errs = panel.apply_to_state()
            self.assertTrue(any("Pattern" in e for e in errs), errs)
            self.assertEqual(state.accents_spec, "")


if __name__ == "__main__":
    unittest.main()
