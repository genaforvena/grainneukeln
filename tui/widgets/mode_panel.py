from textual.app import ComposeResult
from textual.containers import Grid
from textual.widgets import Checkbox, Input, Label, Select, Static

from tui.state import MODES, LIB_POLICIES
from automixer.config import parse_stream_spec


class ModePanel(Static):
    """Mixer selection + per-mode effects — the CLI `amc` knobs the TUI was missing.

    Picks the mixer (rw/q/poly/lib) and edits every effect the CLI exposes: euclid E(k,n) and
    gap-fill (q), the poly stream `pr` spec, the lib policy + cluster count, and the composable
    placement effects snap + swing. Each field maps 1:1 onto AutoMixerConfig and is ignored by the
    mixers it does not apply to — same as on the command line. (`groove_template` is intentionally
    absent: the CLI has no textual form for it either, so there is nothing to reach parity with.)
    """

    def __init__(self, state):
        super().__init__()
        self.state = state

    def compose(self) -> ComposeResult:
        # 4-column grid (label | field | label | field) so the twelve controls stay ~7 rows tall and
        # every panel still fits on one screen — see test_app.test_all_panels_fit_on_screen.
        with Grid():
            yield Label("Mode")
            yield Select(
                [(m, m) for m in MODES], value=self.state.mode,
                allow_blank=False, id="mode")
            yield Label("Lib policy")
            yield Select(
                [(p, p) for p in LIB_POLICIES], value=self.state.lib_policy,
                allow_blank=False, id="lib_policy")

            yield Label("Euclid k (q)")
            yield Input(str(self.state.euclid_k), id="euclid_k", placeholder="k hits")
            yield Label("Euclid n (q)")
            yield Input(str(self.state.euclid_n), id="euclid_n", placeholder="n slots")

            yield Label("Lib clusters")
            yield Input(str(self.state.lib_clusters), id="lib_clusters", placeholder="k")
            yield Label("Swing %")
            yield Input(str(self.state.swing), id="swing", placeholder="0–100 · 66=2:1")

            yield Label("Fill gain dB")
            yield Input(str(self.state.fill_gain_db), id="fill_gain_db", placeholder="-60–0")
            yield Label("Poly (pr)")
            yield Input(
                self.state.streams_spec, id="streams_spec",
                placeholder="3;2 · 4:1-2000;3:6000-15000")

            yield Checkbox("Snap to slot", value=self.state.snap, id="snap")
            yield Checkbox("Gap-fill rests (q)", value=self.state.fill, id="fill")

    def apply_to_state(self):
        """Validate every field and write it back onto the state. Returns a list of error strings;
        an empty list means all fields were valid and applied (same contract as ParamsPanel)."""
        errors = []

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

        mode = self.query_one("#mode", Select).value
        if mode not in MODES:
            errors.append(f"Mode: {mode!r} not one of {', '.join(MODES)}")
            mode = None

        ek = _int("euclid_k", 1, 64, "Euclid k")
        en = _int("euclid_n", 1, 64, "Euclid n")
        if ek is not None and en is not None and ek > en:
            errors.append(f"Euclid: k ({ek}) must be <= n ({en})")
            ek = en = None

        lib_clusters = _int("lib_clusters", 1, 64, "Lib clusters")
        swing = _float("swing", 0.0, 100.0, "Swing %")
        fill_gain = _float("fill_gain_db", -60.0, 0.0, "Fill gain dB")

        lib_policy = self.query_one("#lib_policy", Select).value
        if lib_policy not in LIB_POLICIES:
            errors.append(f"Lib policy: {lib_policy!r} not one of {', '.join(LIB_POLICIES)}")
            lib_policy = None

        # A non-empty poly spec must parse — surface a bad `pr` string as an error instead of
        # letting it blow up mid-grind on the worker thread.
        streams_spec = self.query_one("#streams_spec", Input).value.strip()
        if streams_spec:
            try:
                parse_stream_spec(streams_spec)
            except (ValueError, IndexError) as e:
                errors.append(f"Poly streams: cannot parse {streams_spec!r} ({e})")
                streams_spec = None

        snap = self.query_one("#snap", Checkbox).value
        fill = self.query_one("#fill", Checkbox).value

        if mode is not None:
            self.state.mode = mode
        if ek is not None:
            self.state.euclid_k = ek
        if en is not None:
            self.state.euclid_n = en
        if lib_clusters is not None:
            self.state.lib_clusters = lib_clusters
        if swing is not None:
            self.state.swing = swing
        if fill_gain is not None:
            self.state.fill_gain_db = fill_gain
        if lib_policy is not None:
            self.state.lib_policy = lib_policy
        if streams_spec is not None:
            self.state.streams_spec = streams_spec
        self.state.snap = snap
        self.state.fill = fill
        return errors
