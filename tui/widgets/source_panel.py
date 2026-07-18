from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Static
from textual.message import Message


class SourcePanel(Static):
    class Loaded(Message):
        def __init__(self, cutter):
            self.cutter = cutter
            super().__init__()

    def __init__(self, loader):
        super().__init__()
        self._loader = loader
        self.status_text = "No source loaded"

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Source: local file path or YouTube URL, then Enter")
            yield Input(placeholder="path/to/audio.wav  or  https://youtube.com/...",
                        id="source_input")
            yield Label(self.status_text, id="source_status")

    def on_input_submitted(self, event):
        self.load(event.value)

    def load(self, value):
        value = (value or "").strip()
        if not value:
            self._set_status("Enter a path or URL")
            return
        self._set_status("Loading...")
        try:
            cutter = self._loader(value)
        except Exception as e:
            self._set_status(f"Load failed: {e}")
            return
        beats_attr = getattr(cutter, "beats", None)
        beats = len(beats_attr) if beats_attr is not None else 0   # beats may be a numpy array
        step = getattr(cutter, "step", 0)
        if beats == 0:
            self._set_status("Loaded, but 0 beats — source too steady/silent to latch a pulse")
        else:
            self._set_status(f"Loaded: {beats} beats, step {int(step)} ms")
        self.post_message(self.Loaded(cutter))

    def _set_status(self, text):
        self.status_text = text
        self.query_one("#source_status", Label).update(text)
