"""TUI series runs — the cartesian sweep as driven from the RunPanel's series input.

The grammar is unit-tested in automixer/test_series.py; the CLI wiring in cutter/test_series_cli.py.
These tests verify the TUI-specific glue: the series input persists to state, a malformed spec is
caught BEFORE the worker starts, and a sweep renders N distinguishable files.
"""
import os
import tempfile
import unittest

from tui.state import SessionState
from tui.widgets.run_panel import RunPanel

from textual.app import App, ComposeResult
from textual.widgets import Input


class _Host(App):
    """Host app holding only the RunPanel — the rest of the TUI is not needed to exercise the
    series wiring (state write-back, validation, the runner call)."""
    def __init__(self, state, runner):
        super().__init__()
        self._state = state
        self._runner = runner
        self.finished = None
        self.started_with = None

    def compose(self) -> ComposeResult:
        yield RunPanel(self._state, self._runner)

    def on_run_panel_finished(self, msg):
        self.finished = msg.path


class SeriesInputPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_series_input_writes_to_state(self):
        # Typing into the series input must persist to state.series_spec — a crash mid-typing should
        # not lose it (the same crash-tolerance contract as the other render-option fields).
        state = SessionState(cutter=object(), sample_length_ms=300)
        app = _Host(state, lambda *a: None)
        async with app.run_test() as pilot:
            inp = app.query_one("#series_spec", Input)
            inp.value = "l [/2,/3,/4]"
            await pilot.pause()
            self.assertEqual(state.series_spec, "l [/2,/3,/4]")

    async def test_series_spec_seeded_from_state(self):
        # A restored session (after crash/restart) re-populates the input from state.
        state = SessionState(cutter=object(), sample_length_ms=300, series_spec="s [0.8,1.0]")
        app = _Host(state, lambda *a: None)
        async with app.run_test() as pilot:
            inp = app.query_one("#series_spec", Input)
            self.assertEqual(inp.value, "s [0.8,1.0]")


class SeriesValidationTest(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_series_does_not_invoke_runner(self):
        # A bad series (single value, unknown range, zero step) must surface an error in the log
        # and NEVER call the runner — better to fail upfront than blow up the worker thread.
        state = SessionState(cutter=object(), sample_length_ms=300)
        called = []
        app = _Host(state, lambda *a: called.append(True))
        async with app.run_test() as pilot:
            # A param key + zero-step range — caught by the series expander BEFORE the runner.
            app.query_one("#series_spec", Input).value = "l [100:200:0]"
            await pilot.pause()
            panel = app.query_one(RunPanel)
            panel.start()
            await pilot.pause()
            self.assertEqual(called, [])  # runner never invoked

    async def test_valid_series_invokes_runner(self):
        state = SessionState(cutter=object(), sample_length_ms=300)
        called = []
        def runner(s, on_progress, on_log):
            called.append(True)
            on_log("started")
            return "/tmp/out.mp3"
        app = _Host(state, runner)
        async with app.run_test() as pilot:
            app.query_one("#series_spec", Input).value = "l [/2,/3,/4]"
            await pilot.pause()
            panel = app.query_one(RunPanel)
            panel.start()
            await pilot.pause()
            self.assertEqual(len(called), 1)


class SeriesEndToEndTest(unittest.IsolatedAsyncioTestCase):
    """Full sweep through the real engine — verifies N files are rendered, each labelled with its
    own combination suffix so the operator can tell them apart in the output browser."""
    @classmethod
    def setUpClass(cls):
        from cutter.sample_cut_tool import SampleCutter
        cutter = SampleCutter(os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "assets", "test_audio.mp3")),
            os.path.abspath("output"))
        # Truncate like engine_test — short coherent clip so renders stay fast.
        cutter.audio = cutter.audio[:4000]
        cutter.beats = cutter.beats[cutter.beats < 4000]
        cls.cutter = cutter

    async def test_series_renders_each_combination(self):
        from tui.app import GrainTUI

        class _StubPlayer:
            def stop(self): pass

        with tempfile.TemporaryDirectory() as d:
            state = SessionState(
                cutter=self.cutter, sample_length_ms=300, output_dir=d,
                series_spec="w [2,4] s [0.9,1.1]")
            app = GrainTUI(output_dir=d, player=_StubPlayer())
            app.state = state
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                # Trigger the run via the Run button so the panel's start() validates the spec.
                panel = app.query_one(RunPanel)
                panel.start()
                # Wait for all 4 combinations to land as files.
                import time
                t0 = time.time()
                while time.time() - t0 < 60:
                    await pilot.pause()
                    if len(os.listdir(d)) >= 4:
                        break
                    import asyncio
                    await asyncio.sleep(0.3)
            files = sorted(os.listdir(d))
            self.assertEqual(len(files), 4)
            # Each filename carries its swept params — the operator can read wN_sX directly.
            for w in ("w2", "w4"):
                for s in ("s0.9", "s1.1"):
                    self.assertTrue(any(w in f and s in f for f in files),
                                    f"missing file with {w} and {s}: {files}")


if __name__ == "__main__":
    unittest.main()
