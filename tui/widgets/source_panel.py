import inspect

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option
from textual.message import Message

import youtube.search as yts


class SourcePanel(Static):
    """Load a source. The load (YouTube download + librosa beat-detection) is SLOW, so it runs on a
    worker thread and streams progress to the status line — the UI never freezes, and the app is told
    to keep Run disabled until a real cutter has actually landed (see app.on_source_panel_loaded).
    That ordering is what makes the old "Loaded: N beats" / "Cannot run: No source loaded" race
    impossible: Run only becomes clickable AFTER the Loaded message has set state.cutter.

    Input is classified on submit:
      - ``http(s)://…``               → YouTube URL (downloaded via yt_dlp)
      - ``/path``, ``./x``, ``*.wav`` → local file
      - anything else                 → free-text YouTube SEARCH for "artist + track"

    A search runs ``youtube.search.search`` (ranked for the operator's intent: the
    official Topic/VEVO upload surfaces as #1 even when a fan cover has 50× the
    views). Results land in an ``OptionList`` with #1 highlighted — Enter loads it,
    ↑↓ picks another, or retype to refine. The picker is hidden until a search
    runs so the panel reads as before for path/URL users.
    """

    class Loaded(Message):
        def __init__(self, cutter):
            self.cutter = cutter
            super().__init__()

    class Loading(Message):
        """Emitted when a load starts — the app disables Run until it resolves."""

    class Failed(Message):
        def __init__(self, error):
            self.error = error
            super().__init__()

    def __init__(self, loader, searcher=None):
        super().__init__()
        self._loader = loader
        # ``searcher`` is injectable for tests; the real default calls yt_dlp.
        # Signature: searcher(query) -> list[result-dict] (see youtube.search.search).
        self._searcher = searcher or yts.search
        self.status_text = "No source loaded — enter a file path, YouTube URL, or artist + track"
        self._loading = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Local path · YouTube URL · or artist + track → Enter")
            yield Input(placeholder="path/to/audio.wav   |   https://youtu.be/…   |   Radiohead - Karma Police",
                        id="source_input")
            yield OptionList(id="source_results")
            yield Label(self.status_text, id="source_status")

    def on_mount(self):
        self.border_title = "◈ 1 · source"
        self.border_subtitle = "file · youtube · search"
        # Picker is hidden until a search populates it. ``display=False`` removes
        # it from layout (no empty box on first run).
        try:
            self.query_one("#source_results", OptionList).styles.display = "none"
        except Exception:
            pass

    def on_input_submitted(self, event):
        value = (event.value or "").strip()
        if not value:
            self._set_status("Enter a path, URL, or artist + track, then Enter")
            return
        if yts.is_url(value) or yts.is_local_path(value):
            self._hide_results()
            self.load(value)
        else:
            self._search(value)

    # --- search path ---

    @work(thread=True, exclusive=True, group="search")
    def _search(self, query):
        def stage(text):
            self.app.call_from_thread(self._set_status, text)
        try:
            stage(f"Searching YouTube for “{query}”…")
            # Signature flexibility for tests: 1-arg (query) or 2-arg (query, n).
            try:
                arity = len(inspect.signature(self._searcher).parameters)
            except (TypeError, ValueError):
                arity = 1
            results = self._searcher(query) if arity <= 1 else self._searcher(query, 12)
        except Exception as e:
            self.app.call_from_thread(self._on_search_error, str(e) or e.__class__.__name__)
            return
        self.app.call_from_thread(self._show_results, query, results)

    def _on_search_error(self, err):
        self._set_status(f"Search failed: {err}")
        self.post_message(self.Failed(err or "search error"))

    def _show_results(self, query, results):
        if not results:
            self._set_status(f"No YouTube results for “{query}” — retype to refine")
            self._hide_results()
            return
        ol = self.query_one("#source_results", OptionList)
        ol.clear_options()
        for i, r in enumerate(results, 1):
            ol.add_option(Option(yts.format_result_line(r, idx=i), id=r["url"]))
        ol.styles.display = "block"
        # #1 is the ranker's pick (the official upload, when found). Highlight it
        # so a single Enter proceeds without forcing the operator to arrow down.
        try:
            ol.highlighted = 0
        except Exception:
            pass
        self._set_status(
            f"{len(results)} results for “{query}” — Enter loads #1 · ↑↓ to pick · retype to refine")
        try:
            ol.focus()
        except Exception:
            pass

    def _hide_results(self):
        try:
            ol = self.query_one("#source_results", OptionList)
            ol.clear_options()
            ol.styles.display = "none"
        except Exception:
            pass

    def on_option_list_option_selected(self, event):
        """Enter on a highlighted search result → load that URL through the same
        pipeline as if the operator had pasted it into the Input."""
        url = getattr(event.option, "id", None)
        if not url:
            return
        self._hide_results()
        # Reflect the pick back into the Input so the operator can see what loaded
        # (and Ctrl+L → edit-to-refine works from the chosen URL, not the query).
        try:
            self.query_one("#source_input", Input).value = url
        except Exception:
            pass
        self.load(url)

    # --- load path (unchanged shape; existing tests + app wiring) ---

    def load(self, value):
        value = (value or "").strip()
        if not value:
            self._set_status("Enter a path or URL, then Enter")
            return
        if self._loading:
            self._set_status("Still loading the previous source — one moment…")
            return
        self._loading = True
        self.post_message(self.Loading())
        self._set_status("Loading…")
        self._load_worker(value)

    @work(thread=True, exclusive=True)
    def _load_worker(self, value):
        def stage(text):
            self.app.call_from_thread(self._set_status, text)

        try:
            cutter = self._call_loader(value, stage)
        except Exception as e:  # any load failure keeps the TUI up and legible
            self.app.call_from_thread(self._finish, None, str(e) or e.__class__.__name__)
            return
        self.app.call_from_thread(self._finish, cutter, None)

    def _call_loader(self, value, stage):
        # Back-compat: test loaders are 1-arg (value); the real loader is 2-arg (value, on_stage).
        try:
            arity = len(inspect.signature(self._loader).parameters)
        except (TypeError, ValueError):
            arity = 2
        return self._loader(value, stage) if arity >= 2 else self._loader(value)

    def _finish(self, cutter, err):
        self._loading = False
        if cutter is None:
            self._set_status(f"Load failed: {err}")
            self.post_message(self.Failed(err or "unknown error"))
            return
        beats_attr = getattr(cutter, "beats", None)
        beats = len(beats_attr) if beats_attr is not None else 0   # beats may be a numpy array
        step = getattr(cutter, "step", 0)
        if beats == 0:
            self._set_status("Loaded, but 0 beats — source too steady/silent to latch a pulse")
        else:
            self._set_status(f"✓ Loaded: {beats} beats · default cut {int(step)} ms · ready to grind")
        self.post_message(self.Loaded(cutter))

    def _set_status(self, text):
        self.status_text = text
        try:
            self.query_one("#source_status", Label).update(text)
        except Exception:
            # Status widget not yet mounted (called before compose). Keep the text
            # so on_mount picks it up.
            pass
