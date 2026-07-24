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

    #: Extensions the panel lists. ``.wav`` is here because the WAV checkbox writes one next to
    #: every mp3 — listing only mp3s meant the operator who ticked WAV could not see, play, or
    #: confirm the file they had just asked for.
    EXTS = (".mp3", ".wav")

    #: Cap the rendered list to the newest N. The output dir grows without bound (the grinder never
    #: prunes it — 1000+ files / 2.7 GB in practice), and mounting one widget per file made both the
    #: real TUI startup and every app-level test take 5–12 s just to build the panel. The operator
    #: only ever reaches for a recent render; older ones live on disk, not in this scroll. The cut is
    #: LOUD, never silent — a trailing row states how many more are on disk (no-silent-truncation).
    MAX_LIST = 200

    @staticmethod
    def _describe(path):
        """``name · size · age`` — enough to tell a 4-second dud from a real render without
        leaving the panel, and to spot the one you just made among fifty siblings."""
        try:
            st = os.stat(path)
        except OSError:
            return os.path.basename(path)
        mb = st.st_size / (1024 * 1024)
        size = f"{mb:.1f}M" if mb >= 1 else f"{st.st_size // 1024}K"
        age_s = max(0, int(time.time() - st.st_mtime))
        if age_s < 60:
            age = f"{age_s}s"
        elif age_s < 3600:
            age = f"{age_s // 60}m"
        elif age_s < 86400:
            age = f"{age_s // 3600}h"
        else:
            age = f"{age_s // 86400}d"
        return f"{os.path.basename(path)}  ·  {size} · {age} ago"

    def refresh_list(self):
        lv = self.query_one("#output_list", ListView)
        lv.clear()
        self.paths = []
        if os.path.isdir(self.output_dir):
            files = [os.path.join(self.output_dir, f)
                     for f in os.listdir(self.output_dir) if f.endswith(self.EXTS)]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            total = len(files)
            shown = files[:self.MAX_LIST]
            self.paths = shown
            for p in shown:
                lv.append(ListItem(Label(self._describe(p))))
            hidden = total - len(shown)
            if hidden > 0:
                # A non-playable tail row so the cut is visible, not silent. It is NOT in
                # ``self.paths`` — ``selected_path`` returns None if it is ever highlighted.
                lv.append(ListItem(Label(f"… {hidden} older render(s) on disk (not listed)")))
            if shown:
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
