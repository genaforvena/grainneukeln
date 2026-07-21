import unittest
from textual.app import App, ComposeResult
from textual.widgets import OptionList
from tui.widgets.source_panel import SourcePanel


class _FakeCutter:
    def __init__(self):
        import numpy as np
        self.audio_file_path = "/tmp/x.wav"
        self.beats = np.asarray([0, 500, 1000])   # real type: SampleCutter.beats is a numpy array
        self.step = 500


class _Host(App):
    def __init__(self, loader, searcher=None):
        super().__init__()
        self._loader = loader
        self._searcher = searcher
        self.loaded = None
        self.failed = None

    def compose(self) -> ComposeResult:
        yield SourcePanel(self._loader, searcher=self._searcher)

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


# ─── search-flow tests ─────────────────────────────────────────────────────────


def _fake_results(query, n=12):
    """Deterministic search stand-in. The #1 entry's URL encodes its rank so the
    test can assert which result actually got loaded."""
    return [
        {"url": f"https://youtube.com/watch?v=rank{i}",
         "title": f"{query} — official (rank #{i})",
         "channel": "Artist - Topic" if i == 0 else f"Channel{i}",
         "duration": 200 + i,
         "view_count": 1000 * (n - i),
         "score": float(n - i)}
        for i in range(min(5, n))
    ]


class SourcePanelSearchTest(unittest.IsolatedAsyncioTestCase):
    async def test_free_text_routes_to_search_not_loader(self):
        """The whole point of the feature: typing "artist + track" must NOT be
        handed to the file loader. A search must run, populate the picker, and
        preselect #1 (the ranker's pick)."""
        loaded_urls = []

        def loader(value, on_stage):
            loaded_urls.append(value)
            return _FakeCutter()

        app = _Host(loader, searcher=_fake_results)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            # Free text — not a path, not a URL. Drive via the panel's own handler
            # so the input-classification branch is exercised end-to-end.
            panel.on_input_submitted(
                type("Ev", (), {"value": "Radiohead - Karma Police"})())
            await _settle(app, pilot)

            ol = panel.query_one("#source_results", OptionList)
            self.assertEqual(ol.option_count, 5)
            # #1 is highlighted (so a bare Enter loads it without arrow-keying).
            self.assertEqual(ol.highlighted, 0)
            self.assertIn("Radiohead", panel.status_text)
            # The loader was NOT called by the search — only by an option pick.
            self.assertEqual(loaded_urls, [])

    async def test_picking_result_loads_its_url(self):
        """Selecting a result routes its URL through the normal load pipeline,
        so app.on_source_panel_loaded fires with a real cutter (no special-casing
        downstream)."""
        captured = {}

        def loader(value, on_stage):
            captured["url"] = value
            return _FakeCutter()

        app = _Host(loader, searcher=_fake_results)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel._search("Radiohead Karma Police")
            await _settle(app, pilot)

            ol = panel.query_one("#source_results", OptionList)
            self.assertEqual(ol.highlighted, 0)

            # Simulate Enter on the highlighted #0 option.
            first = ol.get_option_at_index(0)
            panel.on_option_list_option_selected(
                type("Ev", (), {"option": first})())
            await _settle(app, pilot)

            # URL of rank #0 is what got loaded.
            self.assertIn("rank0", captured["url"])
            self.assertIs(app.loaded.__class__, _FakeCutter)

    async def test_search_failure_reports_and_keeps_panel_alive(self):
        """A yt_dlp failure (network / bot-detection) must surface as a Failed
        message and a legible status — not crash the TUI."""
        def boom(query, n=12):
            raise RuntimeError("network down")

        app = _Host(lambda v: _FakeCutter(), searcher=boom)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel._search("anything")
            await _settle(app, pilot)
            self.assertIsNotNone(app.failed)
            self.assertIn("network down", panel.status_text.lower() + (app.failed or "").lower())

    async def test_url_input_bypasses_search(self):
        """Regression: a pasted URL must still go straight to the loader, not the
        search path. The classifier is what protects this."""
        captured = {}
        searches = []

        def loader(value, on_stage):
            captured["url"] = value
            return _FakeCutter()

        def searcher(q):
            searches.append(q)
            return _fake_results(q)

        app = _Host(loader, searcher=searcher)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.on_input_submitted(
                type("Ev", (), {"value": "https://youtube.com/watch?v=abc"})())
            await _settle(app, pilot)

            self.assertIn("abc", captured["url"])   # loader got the URL
            self.assertEqual(searches, [])           # search never ran


if __name__ == "__main__":
    unittest.main()

