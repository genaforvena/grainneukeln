from textual.app import ComposeResult
from textual.containers import Grid
from textual.widgets import Input, Label, Static


class ParamsPanel(Static):
    def __init__(self, state):
        super().__init__()
        self.state = state

    def compose(self) -> ComposeResult:
        with Grid():
            yield Label("Speed (0.1-10)")
            yield Input(str(self.state.speed), id="speed")
            yield Label("Sample speed (0.1-10)")
            yield Input(str(self.state.sample_speed), id="sample_speed")
            yield Label("Window divider (1-10)")
            yield Input(str(self.state.window_divider), id="window_divider")
            yield Label("Sample length (ms)")
            yield Input(str(self.state.sample_length_ms), id="sample_length")

    def apply_to_state(self):
        errors = []

        def _float(field, lo, hi, label):
            raw = self.query_one(f"#{field}", Input).value.strip()
            try:
                v = float(raw)
            except ValueError:
                errors.append(f"{label}: not a number ({raw!r})")
                return None
            if not (lo <= v <= hi):
                errors.append(f"{label}: {v} out of range {lo}-{hi}")
                return None
            return v

        def _int(field, lo, hi, label):
            raw = self.query_one(f"#{field}", Input).value.strip()
            try:
                v = int(raw)
            except ValueError:
                errors.append(f"{label}: not an integer ({raw!r})")
                return None
            if not (lo <= v <= hi):
                errors.append(f"{label}: {v} out of range {lo}-{hi}")
                return None
            return v

        speed = _float("speed", 0.1, 10.0, "Speed")
        ss = _float("sample_speed", 0.1, 10.0, "Sample speed")
        wd = _int("window_divider", 1, 10, "Window divider")
        sl = _int("sample_length", 1, 10_000_000, "Sample length")

        if speed is not None:
            self.state.speed = speed
        if ss is not None:
            self.state.sample_speed = ss
        if wd is not None:
            self.state.window_divider = wd
        if sl is not None:
            self.state.sample_length_ms = sl
        return errors
