import unittest
from textual.app import App, ComposeResult
from textual.widgets import Input
from tui.state import SessionState
from tui.widgets.params_panel import ParamsPanel, resolve_length


class ResolveLengthTest(unittest.TestCase):
    def test_divide_transforms_current(self):
        self.assertEqual(resolve_length("/2", 500), (250, None))   # eighth
        self.assertEqual(resolve_length("/3", 500), (167, None))   # triplet (rounded)
        self.assertEqual(resolve_length("*2", 500), (1000, None))  # half note

    def test_bare_number_is_absolute(self):
        self.assertEqual(resolve_length("320", 500), (320, None))

    def test_chaining_halves_twice(self):
        v1, _ = resolve_length("/2", 500)
        v2, _ = resolve_length("/2", v1)
        self.assertEqual(v2, 125)  # /2 then /2 == /4

    def test_clamped_to_at_least_one_ms(self):
        self.assertEqual(resolve_length("/1000", 500), (1, None))

    def test_garbage_and_div_zero_report(self):
        self.assertIsNone(resolve_length("beat", 500)[0])
        self.assertIsNone(resolve_length("/0", 500)[0])


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

    async def test_slash_two_transforms_current_at_run(self):
        state = SessionState()
        state.sample_length_ms = 500  # seeded from the beat on load
        app = _Host(state)
        async with app.run_test() as pilot:
            panel = app.query_one(ParamsPanel)
            panel.query_one("#sample_length", Input).value = "/2"
            errs = panel.apply_to_state()
            self.assertEqual(errs, [])
            self.assertEqual(state.sample_length_ms, 250)
            # resolved value is reflected back into the field so it can be chained
            self.assertEqual(panel.query_one("#sample_length", Input).value, "250")

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

    async def test_env_rv_inputs_render_current_state_values(self):
        state = SessionState(env_pct=12.0, reverse_prob=0.25)
        app = _Host(state)
        async with app.run_test() as pilot:
            panel = app.query_one(ParamsPanel)
            self.assertEqual(panel.query_one("#env_pct", Input).value, "12.0")
            self.assertEqual(panel.query_one("#reverse_prob", Input).value, "0.25")

    async def test_env_rv_apply_to_state(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test() as pilot:
            panel = app.query_one(ParamsPanel)
            panel.query_one("#env_pct", Input).value = "20"
            panel.query_one("#reverse_prob", Input).value = "0.6"
            errs = panel.apply_to_state()
            self.assertEqual(errs, [])
            self.assertEqual(state.env_pct, 20.0)
            self.assertEqual(state.reverse_prob, 0.6)

    async def test_env_pct_out_of_range_reported_not_written(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test() as pilot:
            panel = app.query_one(ParamsPanel)
            panel.query_one("#env_pct", Input).value = "80"   # > 50
            errs = panel.apply_to_state()
            self.assertTrue(any("envelope" in e.lower() for e in errs))
            self.assertEqual(state.env_pct, 8.0)              # unchanged (default)

    async def test_reverse_prob_out_of_range_reported_not_written(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test() as pilot:
            panel = app.query_one(ParamsPanel)
            panel.query_one("#reverse_prob", Input).value = "1.5"   # > 1.0
            errs = panel.apply_to_state()
            self.assertTrue(any("reverse" in e.lower() for e in errs))
            self.assertEqual(state.reverse_prob, 0.0)         # unchanged (default)
