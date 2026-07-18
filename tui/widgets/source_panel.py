import inspect

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Static
from textual.message import Message


class SourcePanel(Static):
    """Load a source. The load (YouTube download + librosa beat-detection) is SLOW, so it runs on a
    worker thread and streams progress to the status line — the UI never freezes, and the app is told
    to keep Run disabled until a real cutter has actually landed (see app.on_source_panel_loaded).
    That ordering is what makes the old "Loaded: N beats" / "Cannot run: No source loaded" race
    impossible: Run only becomes clickable AFTER the Loaded message has set state.cutter."""

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

    def __init__(self, loader):
        super().__init__()
        self._loader = loader
        self.status_text = "No source loaded — enter a file path or YouTube URL above, then Enter"
        self._loading = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Local file path, or a YouTube URL — then press Enter")
            yield Input(placeholder="path/to/audio.wav   or   https://youtube.com/watch?v=…",
                        id="source_input")
            yield Label(self.status_text, id="source_status")

    def on_mount(self):
        self.border_title = "◈ 1 · source"
        self.border_subtitle = "file · youtube"

    def on_input_submitted(self, event):
        self.load(event.value)

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
        self.query_one("#source_status", Label).update(text)
