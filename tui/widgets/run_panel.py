from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, ProgressBar, RichLog, Static
from textual.message import Message


class RunPanel(Static):
    class Finished(Message):
        def __init__(self, path):
            self.path = path
            super().__init__()

    def __init__(self, state, runner):
        super().__init__()
        self.state = state
        self._runner = runner

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="run_options"):
                yield Checkbox("WAV", value=self.state.wav_export, id="opt_wav",
                               tooltip="Also export a .wav alongside the .mp3 (set_wav_enabled)")
                yield Checkbox("Verbose", value=self.state.verbose, id="opt_verbose",
                               tooltip="Pass is_verbose_mode_enabled to the mixers")
                yield Checkbox("Self-feed", value=self.state.self_feed, id="opt_self_feed",
                               tooltip="After the grind, reload the exported mp3 as the source (aminf)")
            # Series spec (2026-07-19): sweep one or more amc params across a list/range. Empty =
            # single-shot grind; non-empty = the runner expands the cartesian product and iterates
            # one render per combination. The hint string shows the grammar inline so the operator
            # does not need to leave the TUI to look it up. Brackets are ESCAPED because Textual
            # parses ``[...]`` as a markup tag — the literal series syntax would otherwise crash.
            yield Label("Series (optional) · l \\[/2,/3\\] · s \\[0.8:1.2:0.2\\] · m \\[rw,q\\]",
                        id="series_label")
            yield Input(self.state.series_spec, id="series_spec",
                        placeholder="blank = one render;  l [/2,/3,/4]  → 3 renders")
            yield Button("Run grind — load a source first", id="run_btn",
                         variant="primary", disabled=True)
            yield ProgressBar(total=100, show_eta=False, id="run_progress")
            yield RichLog(id="run_log", max_lines=200, wrap=True)

    def on_mount(self):
        self.border_title = "◈ 3 · run"
        self.border_subtitle = "ctrl+r · i: info"

    def set_ready(self, ready, reason="load a source first"):
        """Gate the Run button on whether a source is actually loaded. Keeping Run un-clickable until
        a cutter has landed is what makes the old 'Loaded / No source loaded' contradiction impossible."""
        btn = self.query_one("#run_btn", Button)
        btn.disabled = not ready
        btn.label = "Run grind  (Ctrl+R)" if ready else f"Run grind — {reason}"

    def on_checkbox_changed(self, event):
        """Sync the three render-option checkboxes straight onto state — they take effect on the
        next Run, no separate apply step needed (they are booleans, nothing to validate)."""
        cmap = {"opt_wav": "wav_export", "opt_verbose": "verbose", "opt_self_feed": "self_feed"}
        attr = cmap.get(event.checkbox.id)
        if attr:
            setattr(self.state, attr, event.value)

    def on_input_changed(self, event):
        # Persist the series spec as the operator types — a crash mid-typing should not lose it.
        if event.input.id == "series_spec":
            self.state.series_spec = event.value

    def on_button_pressed(self, event):
        if event.button.id == "run_btn":
            self.start()

    def start(self):
        ok, reason = self.state.is_runnable()
        if not ok:
            self._log(f"Cannot run: {reason}")
            return
        # Validate the series spec before kicking off — a malformed bracket ([1:5] / unknown param
        # / zero step) should surface as an actionable error, not blow up the worker thread.
        from automixer.series import expand_amc_series, SeriesError
        spec = (self.state.series_spec or "").strip()
        if spec:
            tokens = ["amc"] + spec.split()
            try:
                combos = expand_amc_series(tokens)
            except SeriesError as e:
                self._log(f"Series error: {e}")
                return
            n = len(combos)
            if n == 1:
                self._log("Series spec parsed to a single combination — running one render.")
            else:
                self._log(f"Series armed: {n} combinations queued.")
        self.query_one("#run_btn", Button).disabled = True
        self._log("Running...")
        try:
            path = self._runner(self.state, self._on_progress, self._log)
        except Exception as e:
            self._log(f"Run failed: {e}")
            self.query_one("#run_btn", Button).disabled = False
            return
        if path is not None:
            self._on_finished(path)

    def _on_progress(self, fraction):
        self.query_one("#run_progress", ProgressBar).update(progress=fraction * 100)

    def _log(self, text):
        # The grind worker posts log lines from its thread; if the panel has been torn down
        # (worker completes after the app/test exited), the query resolves to nothing. Best-effort:
        # drop the line rather than crash on teardown-order.
        try:
            self.query_one("#run_log", RichLog).write(text)
        except Exception:
            pass

    def _on_finished(self, path):
        try:
            self._log(f"Done: {path}")
            self.query_one("#run_btn", Button).disabled = False
        except Exception:
            pass
        self.post_message(self.Finished(path))
