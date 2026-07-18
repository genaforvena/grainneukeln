from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Label, Static
from textual.message import Message
from tui.state import TrackSpec


class TracksPanel(Static):
    BINDINGS = [("a", "add", "Add track"), ("d", "remove", "Remove track")]

    class Changed(Message):
        def __init__(self, tracks):
            self.tracks = tracks
            super().__init__()

    def __init__(self, tracks):
        super().__init__()
        self._tracks = list(tracks)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Tracks (multitrack)  —  a: add   d: remove   enter: edit")
            yield DataTable(id="tracks_table", cursor_type="row")

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("#", "low Hz", "high Hz")
        self._refresh()

    @property
    def tracks(self):
        return list(self._tracks)

    def _refresh(self):
        table = self.query_one(DataTable)
        cursor = table.cursor_row or 0
        table.clear()
        for i, t in enumerate(self._tracks):
            table.add_row(str(i + 1), str(t.low), str(t.high))
        if self._tracks:
            table.move_cursor(row=min(cursor, len(self._tracks) - 1))
        self.border_title = f"Tracks ({len(self._tracks)})"
        self.post_message(self.Changed(self.tracks))

    def add_track(self):
        self._tracks.append(TrackSpec(0, 15000))
        self._refresh()

    def remove_selected(self):
        if len(self._tracks) <= 1:
            return
        idx = self.query_one(DataTable).cursor_row
        if idx is not None and 0 <= idx < len(self._tracks):
            self._tracks.pop(idx)
            self._refresh()

    def set_selected_range(self, low, high):
        idx = self.query_one(DataTable).cursor_row
        if idx is not None and 0 <= idx < len(self._tracks):
            self._tracks[idx] = TrackSpec(int(low), int(high))
            self._refresh()

    def action_add(self):
        self.add_track()

    def action_remove(self):
        self.remove_selected()
