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

    async def test_self_feed_reloads_exported_mix_as_source(self):
        # `aminf` parity: with self-feed on, a finished grind reloads the exported mp3 as the
        # source — the creative loop where each grind feeds the next.
        reloaded_paths = []
        first_cutter = _FakeCutter()
        second_cutter = _FakeCutter()
        second_cutter.audio_file_path = "/tmp/grind.mp3"
        def fake_loader(value, on_stage=None):
            reloaded_paths.append(value)
            return second_cutter if value.endswith(".mp3") else first_cutter
        app = GrainTUI(output_dir="output", loader=fake_loader, player=lambda p: None)
        async with app.run_test() as pilot:
            from tui.widgets.source_panel import SourcePanel
            from tui.widgets.run_panel import RunPanel
            # Land the initial source, then flip self-feed on.
            app.query_one(SourcePanel).post_message(SourcePanel.Loaded(first_cutter))
            await pilot.pause()
            app.state.self_feed = True
            # Simulate a finished grind → should drive a reload of the exported path. Pump the
            # Finished message FIRST so on_run_panel_finished runs and starts the reload worker
            # before we await it — otherwise wait_for_complete() sees no worker and returns before
            # the Loaded(second_cutter) cascade has a chance to swap state.cutter.
            app.query_one(RunPanel).post_message(RunPanel.Finished("/tmp/grind.mp3"))
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIn("/tmp/grind.mp3", reloaded_paths)
            self.assertIs(app.state.cutter, second_cutter)   # cutter actually swapped

    async def test_self_feed_off_does_not_reload(self):
        first_cutter = _FakeCutter()
        reloaded_paths = []
        def fake_loader(value, on_stage=None):
            reloaded_paths.append(value)
            return first_cutter
        app = GrainTUI(output_dir="output", loader=fake_loader, player=lambda p: None)
        async with app.run_test() as pilot:
            from tui.widgets.source_panel import SourcePanel
            from tui.widgets.run_panel import RunPanel
            app.query_one(SourcePanel).post_message(SourcePanel.Loaded(first_cutter))
            await pilot.pause()
            app.query_one(RunPanel).post_message(RunPanel.Finished("/tmp/out.mp3"))
            await pilot.pause()
            self.assertEqual(reloaded_paths, [])   # no reload when self-feed is off

    async def test_info_dumps_config_to_run_log(self):
        # `amc info` + `info` parity: pressing `i` writes the live source + grind config to the log.
        app = GrainTUI(output_dir="output")
        async with app.run_test() as pilot:
            from textual.widgets import RichLog
            from tui.widgets.source_panel import SourcePanel
            app.query_one(SourcePanel).post_message(SourcePanel.Loaded(_FakeCutter()))
            await pilot.pause()
            app.state.mode = "q"
            app.state.euclid_k = 3
            app.state.euclid_n = 8
            app.action_info()
            await pilot.pause()
            lines = "\n".join(str(l) for l in app.query_one("#run_log", RichLog).lines)
            self.assertIn("Source:", lines)
            self.assertIn("mode=q", lines)
            self.assertIn("E(3,8)", lines)
