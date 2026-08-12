from textual.app import ComposeResult
from textual.containers import Grid
from textual.widgets import Checkbox, Input, Label, Select, Static

from tui.state import MODES, LIB_POLICIES
from automixer.config import parse_stream_spec
# The one shared pattern parser (see tui/amc.py) — the panel validates through it rather than
# re-reading `pat`/`acc` itself, so a name that works on the command line works here by construction.
from automixer.iterators.patterns import PatternError, parse_accents, resolve_pattern


class ModePanel(Static):
    """Mixer selection + per-mode effects — the CLI `amc` knobs the TUI was missing.

    Picks the mixer (rw/q/poly/lib) and edits every effect the CLI exposes: euclid E(k,n), the
    cyclic pattern engine (`pat`/`cyc`/`rot`/`acc`) and gap-fill (q), the poly stream `pr` spec, the
    lib policy + cluster count, and the composable placement effects snap + swing. Each field maps
    1:1 onto AutoMixerConfig and is ignored by the mixers it does not apply to — same as on the
    command line. (`groove_template` is intentionally absent: the CLI has no textual form for it
    either, so there is nothing to reach parity with.)
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

            # Cyclic pattern engine (q). Blank Pattern = the euclid k/n above; a name/spec here
            # REPLACES them. Cycle/Rotate/Accents left blank fall back to the named pattern's own
            # library defaults, and apply to the euclid grid when Pattern is blank — same as `amc`.
            yield Label("Pattern (pat)")
            yield Input(self.state.pattern_spec, id="pattern_spec",
                        placeholder="bembe · clave32 · x..x..x. · +2,2,2,3")
            yield Label("Cycle beats (cyc)")
            yield Input(
                "" if self.state.cycle_beats is None else f"{float(self.state.cycle_beats):g}",
                id="cycle_beats", placeholder="blank = pattern default")

            yield Label("Rotate (rot)")
            yield Input(str(self.state.pattern_rot), id="pattern_rot", placeholder="0 · slots")
            yield Label("Accents dB (acc)")
            yield Input(self.state.accents_spec, id="accents_spec",
                        placeholder="0,-9,-5 · cycled over the pattern")

            yield Checkbox("Snap to slot", value=self.state.snap, id="snap")
            yield Checkbox("Gap-fill rests (q)", value=self.state.fill, id="fill")

    def refresh_from_state(self):
        """Re-seed every control from the state (see ParamsPanel.refresh_from_state for why)."""
        for field, value in (("euclid_k", str(self.state.euclid_k)),
                             ("euclid_n", str(self.state.euclid_n)),
                             ("lib_clusters", str(self.state.lib_clusters)),
                             ("swing", f"{self.state.swing:g}"),
                             ("fill_gain_db", f"{self.state.fill_gain_db:g}"),
                             ("streams_spec", self.state.streams_spec),
                             ("pattern_spec", self.state.pattern_spec),
                             # Blank, not "1" — an unset cyc means "take the pattern's own default",
                             # and showing a number the state does not hold is the two-surfaces-
                             # disagreeing bug this method exists to prevent.
                             ("cycle_beats", "" if self.state.cycle_beats is None
                              else f"{float(self.state.cycle_beats):g}"),
                             ("pattern_rot", str(self.state.pattern_rot)),
                             ("accents_spec", self.state.accents_spec)):
            try:
                self.query_one(f"#{field}", Input).value = value
            except Exception:
                pass
        for field, value in (("mode", self.state.mode), ("lib_policy", self.state.lib_policy)):
            try:
                self.query_one(f"#{field}", Select).value = value
            except Exception:
                pass
        for field, value in (("snap", self.state.snap), ("fill", self.state.fill)):
            try:
                self.query_one(f"#{field}", Checkbox).value = value
            except Exception:
                pass

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

        # Cyclic pattern engine. Blank is the legitimate "unset" for all four (like the seed field),
        # so blankness is not an error — but a NON-blank spec that cannot be read is, and it must not
        # reach the state: a rejected `pat` that silently left the euclid grid in place would render
        # a plausible groove and never mention that the clave asked for did not arrive.
        pattern_spec = self.query_one("#pattern_spec", Input).value.strip()
        accents_spec = self.query_one("#accents_spec", Input).value.strip()
        cyc_raw = self.query_one("#cycle_beats", Input).value.strip()
        cycle_beats, cyc_ok = None, True
        if cyc_raw:
            cycle_beats = _float("cycle_beats", 0.01, 64.0, "Cycle beats")
            cyc_ok = cycle_beats is not None
        rot_raw = self.query_one("#pattern_rot", Input).value.strip()
        pattern_rot, rot_ok = 0, True
        if rot_raw:
            pattern_rot = _int("pattern_rot", -256, 256, "Rotate")
            rot_ok = pattern_rot is not None
        pattern_ok = True
        try:
            if pattern_spec:
                resolve_pattern(pattern_spec, cyc=cycle_beats if cyc_ok else None,
                                rot=pattern_rot if rot_ok else 0, acc=accents_spec or None)
            elif accents_spec:
                parse_accents(accents_spec)
        except PatternError as e:
            errors.append(f"Pattern: {e}")
            pattern_ok = False

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
        if pattern_ok:
            self.state.pattern_spec = pattern_spec
            self.state.accents_spec = accents_spec
        if cyc_ok:
            self.state.cycle_beats = cycle_beats
        if rot_ok:
            self.state.pattern_rot = pattern_rot
        self.state.snap = snap
        self.state.fill = fill
        return errors
