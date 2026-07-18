import os
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, ListItem, ListView, Static


class OutputPanel(Static):
    BINDINGS = [("p", "play", "Play"), ("g", "refresh", "Refresh")]

    def __init__(self, output_dir, player):
        super().__init__()
        self.output_dir = output_dir
        self._player = player
        self.paths = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Outputs  —  p: play   g: refresh")
            yield ListView(id="output_list")

    def on_mount(self):
        self.refresh_list()

    def refresh_list(self):
        lv = self.query_one("#output_list", ListView)
        lv.clear()
        self.paths = []
        if os.path.isdir(self.output_dir):
            files = [os.path.join(self.output_dir, f)
                     for f in os.listdir(self.output_dir) if f.endswith(".mp3")]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            self.paths = files
            for p in files:
                lv.append(ListItem(Label(os.path.basename(p))))
            if files:
                lv.index = 0   # highlight the newest so play/preview has a target

    def play_selected(self):
        lv = self.query_one("#output_list", ListView)
        idx = lv.index
        if idx is None or not (0 <= idx < len(self.paths)):
            return
        path = self.paths[idx]
        try:
            self._player(path)
        except Exception as e:
            # Headless box with no audio sink: don't crash the TUI — surface the path to copy.
            self.notify(f"Can't play here ({e}). File: {path}", severity="warning", timeout=8)

    def action_play(self):
        self.play_selected()

    def action_refresh(self):
        self.refresh_list()
