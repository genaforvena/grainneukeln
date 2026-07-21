from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label, Static
from textual.message import Message
from tui.state import TrackSpec


class TracksPanel(Static):
    """Multitrack band editor. Each track is a low..high Hz band the grinder renders in parallel; the
    mix is the sum. 'a' adds a track, 'd' removes the selected one, and the low/high inputs + Set
    retune the selected row — so a real multi-band grind is buildable from the TUI, not just the CLI."""

    BINDINGS = [("a", "add", "Add track"), ("d", "remove", "Remove track"),
                ("t", "toggle_source", "Toggle source A/B")]

    class Changed(Message):
        def __init__(self, tracks):
            self.tracks = tracks
            super().__init__()

    def __init__(self, tracks):
        super().__init__()
        self._tracks = list(tracks)
        self.status_text = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Bands (multitrack)  —  a add · d remove · t toggle A/B · edit low/high + Set")
            yield DataTable(id="tracks_table", cursor_type="row")
            with Horizontal(id="track_edit"):
                yield Input("0", id="track_low", type="integer")
                yield Input("15000", id="track_high", type="integer")
                yield Button("Set band", id="track_set", variant="default")
            yield Label("", id="track_status")

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("#", "low Hz", "high Hz", "src")
        self._refresh()

    @property
    def tracks(self):
        return list(self._tracks)

    def _refresh(self):
        table = self.query_one(DataTable)
        cursor = table.cursor_row or 0
        table.clear()
        for i, t in enumerate(self._tracks):
            table.add_row(str(i + 1), str(t.low), str(t.high), "B" if t.source2 else "A")
        if self._tracks:
            table.move_cursor(row=min(cursor, len(self._tracks) - 1))
        self.border_title = f"◈ bands ({len(self._tracks)})"
        self.post_message(self.Changed(self.tracks))

    def _sync_inputs_to_cursor(self):
        idx = self.query_one(DataTable).cursor_row
        if idx is not None and 0 <= idx < len(self._tracks):
            t = self._tracks[idx]
            self.query_one("#track_low", Input).value = str(t.low)
            self.query_one("#track_high", Input).value = str(t.high)

    def on_data_table_row_highlighted(self, event):
        self._sync_inputs_to_cursor()

    def on_button_pressed(self, event):
        if event.button.id == "track_set":
            self._apply_edit()

    def on_input_submitted(self, event):
        if event.input.id in ("track_low", "track_high"):
            self._apply_edit()

    def _set_status(self, text):
        self.status_text = text
        self.query_one("#track_status", Label).update(text)

    def _apply_edit(self):
        try:
            low = int(self.query_one("#track_low", Input).value.strip())
            high = int(self.query_one("#track_high", Input).value.strip())
        except ValueError:
            self._set_status("Band needs whole numbers (Hz)")
            return
        if not (0 <= low < high):
            self._set_status(f"Invalid band: need 0 ≤ low < high (got {low}..{high})")
            return
        self.set_selected_range(low, high)
        self._set_status(f"Set band → {low}..{high} Hz")

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

    def toggle_selected_source(self):
        idx = self.query_one(DataTable).cursor_row
        if idx is not None and 0 <= idx < len(self._tracks):
            t = self._tracks[idx]
            self._tracks[idx] = TrackSpec(t.low, t.high, not t.source2)
            self._refresh()
            self._set_status(f"Track {idx + 1} source → {'B' if self._tracks[idx].source2 else 'A'}")

    def action_toggle_source(self):
        self.toggle_selected_source()

    def action_add(self):
        self.add_track()

    def action_remove(self):
        self.remove_selected()
