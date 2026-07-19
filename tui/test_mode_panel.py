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


if __name__ == "__main__":
    unittest.main()
