import unittest
from textual.app import App, ComposeResult
from tui.widgets.source_panel import SourcePanel


class _FakeCutter:
    def __init__(self):
        import numpy as np
        self.audio_file_path = "/tmp/x.wav"
        self.beats = np.asarray([0, 500, 1000])   # real type: SampleCutter.beats is a numpy array
        self.step = 500


class _Host(App):
    def __init__(self, loader):
        super().__init__()
        self._loader = loader
        self.loaded = None

    def compose(self) -> ComposeResult:
        yield SourcePanel(self._loader)

    def on_source_panel_loaded(self, msg):
        self.loaded = msg.cutter


class SourcePanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_successful_load_posts_message(self):
        cutter = _FakeCutter()
        app = _Host(lambda v: cutter)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.load("/tmp/x.wav")
            await pilot.pause()
            self.assertIs(app.loaded, cutter)

    async def test_failed_load_stays_up_and_reports(self):
        def boom(v):
            raise ValueError("bad file")
        app = _Host(boom)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.load("/nope")
            await pilot.pause()
            self.assertIsNone(app.loaded)
            self.assertIn("bad file", panel.status_text.lower())
