import unittest
from textual.app import App, ComposeResult
from textual.widgets import Input
from tui.state import SessionState
from tui.widgets.params_panel import ParamsPanel


class _Host(App):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        yield ParamsPanel(self._state)


class ParamsPanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_valid_values_write_back(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test() as pilot:
            panel = app.query_one(ParamsPanel)
            panel.query_one("#speed", Input).value = "1.5"
            panel.query_one("#sample_speed", Input).value = "0.5"
            panel.query_one("#window_divider", Input).value = "6"
            panel.query_one("#sample_length", Input).value = "480"
            errs = panel.apply_to_state()
            self.assertEqual(errs, [])
            self.assertEqual(state.speed, 1.5)
            self.assertEqual(state.window_divider, 6)
            self.assertEqual(state.sample_length_ms, 480)

    async def test_out_of_range_reported_not_written(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test() as pilot:
            panel = app.query_one(ParamsPanel)
            panel.query_one("#speed", Input).value = "99"    # > 10.0
            panel.query_one("#window_divider", Input).value = "abc"
            errs = panel.apply_to_state()
            self.assertTrue(any("speed" in e.lower() for e in errs))
            self.assertTrue(any("divider" in e.lower() for e in errs))
            self.assertEqual(state.speed, 1.0)               # unchanged
