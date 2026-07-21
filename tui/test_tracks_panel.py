import unittest
from textual.app import App, ComposeResult
from tui.state import TrackSpec
from tui.widgets.tracks_panel import TracksPanel


class _Host(App):
    def __init__(self, tracks):
        super().__init__()
        self._tracks = tracks

    def compose(self) -> ComposeResult:
        yield TracksPanel(self._tracks)


class TracksPanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_add_and_remove(self):
        app = _Host([TrackSpec(0, 15000)])
        async with app.run_test() as pilot:
            panel = app.query_one(TracksPanel)
            self.assertEqual(len(panel.tracks), 1)
            panel.add_track()
            await pilot.pause()
            self.assertEqual(len(panel.tracks), 2)
            panel.remove_selected()
            await pilot.pause()
            self.assertEqual(len(panel.tracks), 1)

    async def test_never_below_one(self):
        app = _Host([TrackSpec(0, 15000)])
        async with app.run_test() as pilot:
            panel = app.query_one(TracksPanel)
            panel.remove_selected()
            await pilot.pause()
            self.assertEqual(len(panel.tracks), 1)   # floor at one track

    async def test_edit_range(self):
        app = _Host([TrackSpec(0, 15000)])
        async with app.run_test() as pilot:
            panel = app.query_one(TracksPanel)
            panel.set_selected_range(200, 400)
            await pilot.pause()
            self.assertEqual((panel.tracks[0].low, panel.tracks[0].high), (200, 400))

    async def test_band_edit_ui_applies_to_selected_row(self):
        from textual.widgets import Button, Input
        app = _Host([TrackSpec(0, 15000)])
        async with app.run_test() as pilot:
            panel = app.query_one(TracksPanel)
            panel.query_one("#track_low", Input).value = "300"
            panel.query_one("#track_high", Input).value = "1200"
            # exercise the Set-button wiring (on_button_pressed -> _apply_edit)
            panel.on_button_pressed(Button.Pressed(panel.query_one("#track_set", Button)))
            await pilot.pause()
            self.assertEqual((panel.tracks[0].low, panel.tracks[0].high), (300, 1200))

    async def test_band_edit_rejects_invalid_range(self):
        from textual.widgets import Button, Input
        app = _Host([TrackSpec(0, 15000)])
        async with app.run_test() as pilot:
            panel = app.query_one(TracksPanel)
            panel.query_one("#track_low", Input).value = "5000"
            panel.query_one("#track_high", Input).value = "100"      # low >= high
            panel.on_button_pressed(Button.Pressed(panel.query_one("#track_set", Button)))
            await pilot.pause()
            self.assertEqual((panel.tracks[0].low, panel.tracks[0].high), (0, 15000))  # unchanged
            self.assertIn("invalid", panel.status_text.lower())

    async def test_new_track_defaults_to_source_a(self):
        app = _Host([TrackSpec(0, 15000)])
        async with app.run_test() as pilot:
            panel = app.query_one(TracksPanel)
            panel.add_track()
            await pilot.pause()
            self.assertFalse(panel.tracks[-1].source2)

    async def test_toggle_source_flips_selected_row(self):
        app = _Host([TrackSpec(0, 15000)])
        async with app.run_test() as pilot:
            panel = app.query_one(TracksPanel)
            self.assertFalse(panel.tracks[0].source2)
            panel.action_toggle_source()
            await pilot.pause()
            self.assertTrue(panel.tracks[0].source2)
            table = panel.query_one("DataTable")
            row = table.get_row_at(0)
            self.assertEqual(row[3], "B")

    async def test_band_edit_preserves_source_toggle(self):
        # Regression: set_selected_range rebuilt the TrackSpec without source2, so editing the Hz
        # band silently reset a B-tagged track back to A.
        app = _Host([TrackSpec(0, 15000)])
        async with app.run_test() as pilot:
            panel = app.query_one(TracksPanel)
            panel.action_toggle_source()
            await pilot.pause()
            panel.set_selected_range(200, 400)
            await pilot.pause()
            self.assertEqual((panel.tracks[0].low, panel.tracks[0].high), (200, 400))
            self.assertTrue(panel.tracks[0].source2, "band edit must not reset the A/B tag")
            table = panel.query_one("DataTable")
            self.assertEqual(table.get_row_at(0)[3], "B")

    async def test_toggle_source_twice_returns_to_a(self):
        app = _Host([TrackSpec(0, 15000)])
        async with app.run_test() as pilot:
            panel = app.query_one(TracksPanel)
            panel.action_toggle_source()
            await pilot.pause()
            panel.action_toggle_source()
            await pilot.pause()
            self.assertFalse(panel.tracks[0].source2)
            table = panel.query_one("DataTable")
            row = table.get_row_at(0)
            self.assertEqual(row[3], "A")
