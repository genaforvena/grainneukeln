import unittest
from textual.app import App, ComposeResult
from textual.widgets import Checkbox
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

    async def test_uxn_enabled_calls_runner_and_skips_series_validation(self):
        """When uxn_enabled is set, start() must delegate straight to the runner and NEVER reach
        the series-spec validation path — an intentionally malformed series_spec (which would
        normally raise a SeriesError and log it) must be silently ignored."""
        calls = []
        state = SessionState(cutter=object(), sample_length_ms=300, uxn_enabled=True,
                             uxn_ticks=4, series_spec="l [100:200:0]")  # zero step -> SeriesError

        def spy_runner(s, on_progress, on_log):
            calls.append(s)
            return "/tmp/uxn-out.mp3"

        app = _Host(state, spy_runner)
        async with app.run_test() as pilot:
            panel = app.query_one(RunPanel)
            panel.start()
            await pilot.pause()
            self.assertEqual(len(calls), 1)          # runner invoked exactly once
            self.assertEqual(app.finished, "/tmp/uxn-out.mp3")

    async def test_render_option_checkboxes_sync_to_state(self):
        """WAV / Verbose / Self-feed / Low-mem checkboxes are the TUI's parity surface for the CLI's
        set_wav_enabled / set_verbose_enabled / aminf / --low-memory — toggling one writes straight
        to state. (The Uxn checkboxes moved to their own panel 2026-07-24 and are tested there.)"""
        state = SessionState(cutter=object(), sample_length_ms=300)
        app = _Host(state, lambda *a: None)
        async with app.run_test() as pilot:
            for cid, attr in (("opt_wav", "wav_export"),
                              ("opt_verbose", "verbose"),
                              ("opt_self_feed", "self_feed"),
                              ("opt_low_memory", "low_memory")):
                cb = app.query_one(f"#{cid}", Checkbox)
                self.assertFalse(getattr(state, attr))   # default off
                cb.value = True
                await pilot.pause()
                self.assertTrue(getattr(state, attr))
                cb.value = False
                await pilot.pause()
                self.assertFalse(getattr(state, attr))
