import unittest
from tui.app import GrainTUI


class _FakeCutter:
    beats = [0, 400, 800]
    step = 400
    audio_file_path = "/tmp/x.wav"


class AppWiringTest(unittest.IsolatedAsyncioTestCase):
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
