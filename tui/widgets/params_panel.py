import re

from textual.app import ComposeResult
from textual.containers import Grid
from textual.widgets import Input, Label, Static

# `/2`, `* 3`, `/1.5` — a transform of the CURRENT sample length (chainable: /2 then /2 = /4).
_OP_RE = re.compile(r"^\s*([*/])\s*(\d+(?:\.\d+)?)\s*$")


def resolve_length(raw, current):
    """Resolve a sample-length field entry to an int ms value.

    Two forms:
      * ``/N`` or ``*N``  → transform the CURRENT value (beat ÷2 = eighth, ÷3 = triplet, ×2 = half).
        The base is whatever is in the field now, which is seeded from the real beat period on load,
        so ``/3`` is a true triplet of the beat. Chainable — apply ``/2`` twice for ``/4``.
      * a bare number     → absolute milliseconds (unchanged behaviour).

    Returns (value:int, error:str|None). Grain length is clamped to >= 1ms.
    """
    m = _OP_RE.match(raw)
    if m:
        op, num = m.group(1), float(m.group(2))
        if num == 0:
            return None, "Sample length: cannot */÷ by 0"
        val = current / num if op == "/" else current * num
        return max(1, int(round(val))), None
    try:
        return max(1, int(round(float(raw.strip())))), None
    except ValueError:
        return None, f"Sample length: not a number or /N, *N ({raw!r})"


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
            yield Label("Sample length (ms) · /2 /3 *2", id="sample_length_label")
            yield Input(str(self.state.sample_length_ms), id="sample_length")
            # The literal "%%" here was an argparse escape that leaked into the rendered label —
            # Textual is not printf, so the operator read "Envelope taper %%". Same in the error
            # strings below.
            yield Label("Envelope taper % (0-50)")
            yield Input(str(self.state.env_pct), id="env_pct")
            yield Label("Reverse probability (0-1)")
            yield Input(str(self.state.reverse_prob), id="reverse_prob")
            yield Label("Seed (blank = random)")
            yield Input("" if self.state.seed is None else str(self.state.seed), id="seed",
                        placeholder="e.g. 42 — same seed + params = identical render")

    def refresh_from_state(self):
        """Re-seed every input from the state — the other half of ``apply_to_state``.

        Without it the amc bar (and the CLI flags that pre-arm the session) would change what Run
        renders while the widgets kept showing the old numbers: two surfaces disagreeing about one
        fact, which is the exact class of bug the Loaded/No-source race was."""
        vals = {
            "speed": f"{self.state.speed:g}",
            "sample_speed": f"{self.state.sample_speed:g}",
            "window_divider": str(self.state.window_divider),
            "sample_length": str(int(self.state.sample_length_ms)),
            "env_pct": f"{self.state.env_pct:g}",
            "reverse_prob": f"{self.state.reverse_prob:g}",
            "seed": "" if self.state.amc_seed() is None else str(self.state.amc_seed()),
        }
        for field, value in vals.items():
            try:
                self.query_one(f"#{field}", Input).value = value
            except Exception:
                pass

    def set_beat(self, beat_ms):
        """Show the beat period in the label so /2 /3 *2 have a visible base."""
        try:
            label = self.query_one("#sample_length_label", Label)
        except Exception:
            return
        if beat_ms and beat_ms > 0:
            label.update(f"Sample length (ms) · beat={beat_ms} · /2 /3 *2")
        else:
            label.update("Sample length (ms) · /2 /3 *2")

    def on_input_submitted(self, event) -> None:
        """Resolve /N *N against the current value on Enter and reflect it back, so the operator
        sees the concrete ms and can chain (type /2, Enter → 250; /2, Enter → 125)."""
        if event.input.id != "sample_length":
            return
        val, err = resolve_length(event.value, self.state.sample_length_ms)
        if err is not None:
            self.notify(err, severity="error", timeout=6)
            return
        self.state.sample_length_ms = val
        event.input.value = str(val)

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
        env_pct = _float("env_pct", 0.0, 50.0, "Envelope taper %")
        reverse_prob = _float("reverse_prob", 0.0, 1.0, "Reverse probability")

        # Seed: blank is a legitimate value (unseeded/legacy), so it is validated separately from
        # the numeric fields — an empty string is not an error, a non-integer is.
        seed_raw = self.query_one("#seed", Input).value.strip()
        seed = None
        seed_ok = True
        if seed_raw:
            try:
                seed = int(seed_raw)
            except ValueError:
                errors.append(f"Seed: not an integer ({seed_raw!r}) — leave blank for unseeded")
                seed_ok = False

        # Sample length accepts /N *N (transform current) as well as a bare number, matching the
        # on-Enter handler — so a value left as "/2" at Run time still resolves instead of erroring.
        sl_input = self.query_one("#sample_length", Input)
        sl, sl_err = resolve_length(sl_input.value, self.state.sample_length_ms)
        if sl_err is not None:
            errors.append(sl_err)
        elif not (1 <= sl <= 10_000_000):
            errors.append(f"Sample length: {sl} out of range 1-10000000")
            sl = None

        if speed is not None:
            self.state.speed = speed
        if ss is not None:
            self.state.sample_speed = ss
        if wd is not None:
            self.state.window_divider = wd
        if env_pct is not None:
            self.state.env_pct = env_pct
        if reverse_prob is not None:
            self.state.reverse_prob = reverse_prob
        if seed_ok:
            self.state.seed = seed
        if sl is not None:
            self.state.sample_length_ms = sl
            sl_input.value = str(sl)
        return errors
