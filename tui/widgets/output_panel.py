import os
import time
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Label, ListItem, ListView, Static

from tui.player import PlaybackState, SEEK_STEP_SEC, _fmt_pos


class OutputPanel(Static):
    """Outputs list + non-blocking playback controller (operator 2026-07-19:
    'start/stop/pause/resume/ff/backwards').

    Bindings fire when this panel has focus (Ctrl+6 to jump here). The status line above the list
    shows the live playback position, refreshing every 500ms via a Textual interval — so the
    operator sees ▶ 0:42 / /tmp/grind.mp3 advancing while the track plays.
    """

    BINDINGS = [
        ("space", "toggle_play", "Play/Pause"),
        ("s", "stop", "Stop"),
        Binding("dot", "seek_forward", "FF 10s", show=False),
        Binding("comma", "seek_back", "Back 10s", show=False),
        ("g", "refresh", "Refresh"),
    ]

    REFRESH_INTERVAL = 0.5   # seconds — the playback position status line tick

    def __init__(self, output_dir, player):
        super().__init__()
        self.output_dir = output_dir
        # Player may be a Player instance (new contract) or a legacy callable ``player(path)`` for
        # back-compat with existing tests. Detect and adapt.
        self._player_obj = player if hasattr(player, "play") else None
        self._player_fn = player if self._player_obj is None else None
        self.paths = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._status_text(), id="playback_status")
            yield Label("Outputs  —  space: play/pause · s: stop · .: ff · ,: back · g: refresh",
                        id="output_hint")
            yield ListView(id="output_list")

    def on_mount(self):
        self.refresh_list()
        # Live-refresh the playback status line — wallclock position advances while playing.
        self.set_interval(self.REFRESH_INTERVAL, self._refresh_status)

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

    @property
    def selected_path(self):
        lv = self.query_one("#output_list", ListView)
        idx = lv.index
        if idx is None or not (0 <= idx < len(self.paths)):
            return None
        return self.paths[idx]

    # --- playback control: routed through Player when available, else legacy callable ---
    def play_selected(self, start_at=0.0):
        path = self.selected_path
        if path is None:
            return
        if self._player_obj is not None:
            try:
                self._player_obj.play(path, start_at=start_at)
            except Exception as e:
                self.notify(f"Can't play here ({e}). File: {path}", severity="warning", timeout=8)
        elif self._player_fn is not None:
            try:
                self._player_fn(path)
            except Exception as e:
                self.notify(f"Can't play here ({e}). File: {path}", severity="warning", timeout=8)
        self._refresh_status()

    def toggle_play(self):
        """space: start if stopped, pause if playing, resume if paused. The one key that always does
        the right thing — matches every other player's spacebar contract."""
        if self._player_obj is None:
            # Legacy callable player has no pause/resume — space = play (the legacy contract).
            self.play_selected()
            return
        st = self._player_obj.state()
        if st["state"] == PlaybackState.PLAYING:
            self._player_obj.pause()
        elif st["state"] == PlaybackState.PAUSED:
            self._player_obj.resume()
        else:
            self.play_selected()

    def stop_playback(self):
        if self._player_obj is not None:
            self._player_obj.stop()
        self._refresh_status()

    def seek_forward(self):
        if self._player_obj is not None:
            self._player_obj.seek(SEEK_STEP_SEC)
        self._refresh_status()

    def seek_back(self):
        if self._player_obj is not None:
            self._player_obj.seek(-SEEK_STEP_SEC)
        self._refresh_status()

    # --- display ---
    def _status_text(self):
        """One-line playback status: ▶/⏸/⏹ + filename + position."""
        if self._player_obj is None:
            return "▶ (no player — space plays selected)"
        st = self._player_obj.state()
        icon = {"playing": "▶", "paused": "⏸", "stopped": "⏹"}.get(st["state"], "·")
        if st["path"]:
            name = os.path.basename(st["path"])
            if st["state"] == PlaybackState.STOPPED:
                return f"{icon} stopped  ·  {name}"
            return f"{icon} {_fmt_pos(st['pos_sec'])}  ·  {name}"
        return f"{icon} nothing loaded — select a file and press space"

    def _refresh_status(self):
        try:
            self.query_one("#playback_status", Label).update(self._status_text())
        except Exception:
            pass   # panel not yet mounted — interval fires once before compose completes

    # --- binding actions ---
    def action_toggle_play(self):
        self.toggle_play()

    def action_stop(self):
        self.stop_playback()

    def action_seek_forward(self):
        self.seek_forward()

    def action_seek_back(self):
        self.seek_back()

    def action_refresh(self):
        self.refresh_list()
