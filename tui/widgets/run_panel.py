from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, ProgressBar, RichLog, Static
from textual.message import Message


class RunPanel(Static):
    class Finished(Message):
        def __init__(self, path):
            self.path = path
            super().__init__()

    def __init__(self, state, runner):
        super().__init__()
        self.state = state
        self._runner = runner

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Button("Run grind — load a source first", id="run_btn",
                         variant="primary", disabled=True)
            yield ProgressBar(total=100, show_eta=False, id="run_progress")
            yield RichLog(id="run_log", max_lines=200, wrap=True)

    def on_mount(self):
        self.border_title = "3 · Run"

    def set_ready(self, ready, reason="load a source first"):
        """Gate the Run button on whether a source is actually loaded. Keeping Run un-clickable until
        a cutter has landed is what makes the old 'Loaded / No source loaded' contradiction impossible."""
        btn = self.query_one("#run_btn", Button)
        btn.disabled = not ready
        btn.label = "Run grind  (Ctrl+R)" if ready else f"Run grind — {reason}"

    def on_button_pressed(self, event):
        if event.button.id == "run_btn":
            self.start()

    def start(self):
        ok, reason = self.state.is_runnable()
        if not ok:
            self._log(f"Cannot run: {reason}")
            return
        self.query_one("#run_btn", Button).disabled = True
        self._log("Running...")
        try:
            path = self._runner(self.state, self._on_progress, self._log)
        except Exception as e:
            self._log(f"Run failed: {e}")
            self.query_one("#run_btn", Button).disabled = False
            return
        if path is not None:
            self._on_finished(path)

    def _on_progress(self, fraction):
        self.query_one("#run_progress", ProgressBar).update(progress=fraction * 100)

    def _log(self, text):
        self.query_one("#run_log", RichLog).write(text)

    def _on_finished(self, path):
        self._log(f"Done: {path}")
        self.query_one("#run_btn", Button).disabled = False
        self.post_message(self.Finished(path))
