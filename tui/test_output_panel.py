import os
import tempfile
import unittest
from textual.app import App, ComposeResult
from tui.widgets.output_panel import OutputPanel


class _Host(App):
    def __init__(self, d, player):
        super().__init__()
        self._d = d
        self._player = player

    def compose(self) -> ComposeResult:
        yield OutputPanel(self._d, self._player)


class OutputPanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_lists_and_plays(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("a.mp3", "b.mp3"):
                with open(os.path.join(d, name), "wb") as f:
                    f.write(b"\x00" * 10)
            played = []
            app = _Host(d, lambda p: played.append(p))
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                await pilot.pause()
                self.assertEqual(len(panel.paths), 2)
                panel.play_selected()
                await pilot.pause()
                self.assertEqual(len(played), 1)
                self.assertTrue(played[0].endswith(".mp3"))
