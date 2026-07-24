"""The amc command bar — type any CLI recipe, the panels update.

This is the TUI's parity bridge (2026-07-24). Before it, reaching a knob meant finding its widget,
and any token nobody had built a widget for was unreachable from the TUI at all. Now the full
grammar is always one keystroke away (Ctrl+E), the panels stay the discoverable surface, and the
line above the bar always states — in the CLI's own vocabulary — exactly what Run will render.

Three behaviours worth naming:

* **A bracketed token arms a series instead of erroring.** ``l [/2,/3]`` is not a value the single
  render path can take, but it IS a legal thing to want, so the bar routes it to the series field
  rather than reporting "l: not a number".
* **A partly-wrong line still applies its good half**, and names every bad token. Retyping a
  20-token recipe because one of them was mistyped is the failure mode this avoids.
* **History (↑/↓)** — recipes are iterated, not written once. Session-local, not persisted;
  the recipe line itself is the durable record and it is checkpointed with the session.
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, Label, Static
from textual.message import Message

from tui.amc import apply_amc, format_amc, is_series


class CommandBar(Static):
    """One-line amc entry + the live recipe readout above it."""

    BINDINGS = [
        Binding("up", "history_prev", "Prev recipe", show=False),
        Binding("down", "history_next", "Next recipe", show=False),
    ]

    class Applied(Message):
        """Raised after a line changes the state, so the app can re-seed every panel from it."""

        def __init__(self, text, errors, series):
            self.text = text
            self.errors = errors
            self.series = series
            super().__init__()

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.history = []
        self._hist_pos = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("", id="recipe_line")
            yield Input(placeholder="amc l /2 w 4 m q c 0,250;900,7000 snap sw 66   ·   Enter applies · ↑ history",
                        id="amc_input")

    def on_mount(self):
        self.border_title = "◈ 7 · amc command bar"
        self.border_subtitle = "ctrl+e · the CLI's own grammar"
        self.refresh_recipe()

    def refresh_recipe(self):
        """Repaint the live recipe line. Called by the app after ANY panel edit, so the line is
        never a stale claim about what Run will do."""
        try:
            self.query_one("#recipe_line", Label).update(format_amc(self.state))
        except Exception:
            pass

    @property
    def recipe(self):
        return format_amc(self.state)

    def on_input_submitted(self, event):
        if event.input.id != "amc_input":
            return
        text = (event.value or "").strip()
        if not text:
            return
        self.history.append(text)
        self._hist_pos = None
        if is_series(text):
            # A bracketed line is a SWEEP, not a value — hand it to the series field verbatim
            # (minus any leading `amc`, which the series runner adds back itself).
            spec = text[4:].strip() if text.startswith("amc ") else text
            self.state.series_spec = spec
            event.input.value = ""
            self.post_message(self.Applied(text, [], series=spec))
            return
        errors = apply_amc(self.state, text)
        event.input.value = ""
        self.refresh_recipe()
        self.post_message(self.Applied(text, errors, series=None))

    def action_history_prev(self):
        if not self.history:
            return
        self._hist_pos = len(self.history) - 1 if self._hist_pos is None \
            else max(0, self._hist_pos - 1)
        self.query_one("#amc_input", Input).value = self.history[self._hist_pos]

    def action_history_next(self):
        if not self.history or self._hist_pos is None:
            return
        if self._hist_pos >= len(self.history) - 1:
            self._hist_pos = None
            self.query_one("#amc_input", Input).value = ""
            return
        self._hist_pos += 1
        self.query_one("#amc_input", Input).value = self.history[self._hist_pos]
