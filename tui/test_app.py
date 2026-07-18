import unittest
from tui.app import GrainTUI


class _FakeCutter:
    beats = [0, 400, 800]
    step = 400
    audio_file_path = "/tmp/x.wav"


class AppWiringTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_panels_fit_on_screen(self):
        # Regression: a bad `height: auto` let Source and Run each fill their whole column, pushing
        # Params/Tracks/Outputs off the bottom (y past the screen). Every panel must be visible.
        from tui.widgets.source_panel import SourcePanel
        from tui.widgets.params_panel import ParamsPanel
        from tui.widgets.tracks_panel import TracksPanel
        from tui.widgets.run_panel import RunPanel
        from tui.widgets.output_panel import OutputPanel
        app = GrainTUI(output_dir="output")
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            for W in (SourcePanel, ParamsPanel, TracksPanel, RunPanel, OutputPanel):
                r = app.query_one(W).region
                self.assertGreater(r.height, 0, f"{W.__name__} has zero height")
                self.assertLessEqual(r.bottom, 40, f"{W.__name__} runs off the bottom (y={r.bottom})")

    async def test_source_loaded_seeds_state(self):
        app = GrainTUI(output_dir="output")
        async with app.run_test() as pilot:
            from tui.widgets.source_panel import SourcePanel
            src = app.query_one(SourcePanel)
            src.post_message(SourcePanel.Loaded(_FakeCutter()))
            await pilot.pause()
            self.assertIsNotNone(app.state.cutter)
            self.assertEqual(app.state.sample_length_ms, 400)  # seeded from step

    async def test_tracks_changed_updates_state(self):
        app = GrainTUI(output_dir="output")
        async with app.run_test() as pilot:
            from tui.widgets.tracks_panel import TracksPanel
            panel = app.query_one(TracksPanel)
            panel.add_track()
            await pilot.pause()
            self.assertEqual(len(app.state.tracks), 2)

    async def test_run_button_gated_on_loaded_source(self):
        # The core "does not work" fix: Run is un-clickable until a source has actually loaded, so
        # "Loaded: N beats" and "No source loaded" can never disagree.
        app = GrainTUI(output_dir="output")
        async with app.run_test() as pilot:
            from textual.widgets import Button
            from tui.widgets.source_panel import SourcePanel
            btn = app.query_one("#run_btn", Button)
            self.assertTrue(btn.disabled)                       # disabled at start
            app.query_one(SourcePanel).post_message(SourcePanel.Loaded(_FakeCutter()))
            await pilot.pause()
            self.assertFalse(btn.disabled)                      # enabled once a source lands
            app.query_one(SourcePanel).post_message(SourcePanel.Failed("boom"))
            await pilot.pause()
            self.assertTrue(btn.disabled)                       # a failed reload re-locks it
            self.assertIsNone(app.state.cutter)

    async def test_real_source_worker_completion_is_not_a_grind_result(self):
        # SourcePanel's load worker is a thread worker too; its completion must NOT drive the run log
        # (the app filters on worker group == "grind").
        loaded = _FakeCutter()
        app = GrainTUI(output_dir="output", loader=lambda v: loaded, player=lambda p: None)
        async with app.run_test() as pilot:
            from textual.widgets import RichLog
            from tui.widgets.source_panel import SourcePanel
            app.query_one(SourcePanel).load("/tmp/x.wav")
            await app.workers.wait_for_complete()
            await pilot.pause()
            log_text = "\n".join(str(l) for l in app.query_one("#run_log", RichLog).lines)
            self.assertNotIn("Done", log_text)                  # no phantom "Done: <cutter>"
            self.assertIsNotNone(app.state.cutter)
