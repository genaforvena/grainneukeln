import unittest
from textual.app import App, ComposeResult
from tui.state import SessionState
from tui.widgets.run_panel import RunPanel


class _Host(App):
    def __init__(self, state, runner):
        super().__init__()
        self._state = state
        self._runner = runner
        self.finished = None

    def compose(self) -> ComposeResult:
        yield RunPanel(self._state, self._runner)

    def on_run_panel_finished(self, msg):
        self.finished = msg.path


class RunPanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_blocks_when_not_runnable(self):
        state = SessionState()   # no cutter -> not runnable
        called = []
        app = _Host(state, lambda s, on_progress, on_log: called.append(True))
        async with app.run_test() as pilot:
            panel = app.query_one(RunPanel)
            panel.start()
            await pilot.pause()
            self.assertEqual(called, [])          # runner never invoked
            self.assertIsNone(app.finished)

    async def test_runs_and_finishes(self):
        state = SessionState(cutter=object(), sample_length_ms=300)

        def fake_runner(s, on_progress, on_log):
            on_log("started")
            on_progress(1.0)
            return "/tmp/out.mp3"

        app = _Host(state, fake_runner)
        async with app.run_test() as pilot:
            panel = app.query_one(RunPanel)
            panel.start()
            await pilot.pause()
            self.assertEqual(app.finished, "/tmp/out.mp3")
