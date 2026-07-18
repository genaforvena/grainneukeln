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
        self.failed = None

    def compose(self) -> ComposeResult:
        yield SourcePanel(self._loader)

    def on_source_panel_loaded(self, msg):
        self.loaded = msg.cutter

    def on_source_panel_failed(self, msg):
        self.failed = msg.error


async def _settle(app, pilot):
    # the load runs on a worker thread now — wait for it before asserting
    await app.workers.wait_for_complete()
    await pilot.pause()


class SourcePanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_successful_load_posts_message(self):
        cutter = _FakeCutter()
        app = _Host(lambda v: cutter)          # 1-arg loader (back-compat) still works
        async with app.run_test() as pilot:
            app.query_one(SourcePanel).load("/tmp/x.wav")
            await _settle(app, pilot)
            self.assertIs(app.loaded, cutter)

    async def test_failed_load_stays_up_and_reports(self):
        def boom(v):
            raise ValueError("bad file")
        app = _Host(boom)
        async with app.run_test() as pilot:
            app.query_one(SourcePanel).load("/nope")
            await _settle(app, pilot)
            self.assertIsNone(app.loaded)
            self.assertEqual(app.failed, "bad file")           # Failed message carries the error
            self.assertIn("bad file", app.query_one(SourcePanel).status_text.lower())

    async def test_progress_stages_stream_to_status(self):
        stages = []

        def loader(value, on_stage):                            # 2-arg loader gets a progress hook
            on_stage("Downloading… 10%")
            on_stage("Detecting beats…")
            return _FakeCutter()

        app = _Host(loader)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.load("https://youtube.com/x")
            await _settle(app, pilot)
            self.assertIs(app.loaded.__class__, _FakeCutter)
            # final status is the loaded summary, and a beats count is shown
            self.assertIn("loaded", panel.status_text.lower())
            self.assertIn("beats", panel.status_text.lower())
