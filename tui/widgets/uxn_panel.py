"""Uxn ROM control — its own panel, with a dry-run preview.

Issue #13's control layer had exactly four cramped, unlabelled widgets squeezed into one row of the
Run panel: a checkbox, a bare ROM path, a bare number, and another checkbox. Nothing said what the
number was, whether the ROM resolved, whether ``uxncli`` had ever been built, or what the sequence
would do — and finding out cost N full grinds, because starting the run was the only way to see the
ROM's output. Since the ROM's own arithmetic is microseconds and touches no audio, that was N
renders spent answering a question a dry run answers instantly.

So this panel: every control labelled, the ROM path resolved and CHECKED on screen, and a
**Preview** that ticks the ROM without rendering and prints the plan — including the mode axis
(2026-07-24) that makes a run move through cutting algorithms (rw → q → poly → lib) rather than
just through one algorithm's knobs. The preview is also the ROM's smoke test: a hand-written ROM
that emits nothing fails here, in a second, instead of on tick 0 of an hour-long run.
"""

import os

from textual import work
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, RichLog, Static


class UxnPanel(Static):
    """Enable / ROM / ticks / closed-loop + a dry-run preview of the ROM's plan."""

    def __init__(self, state):
        super().__init__()
        self.state = state

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="uxn_toggles"):
                yield Checkbox("Drive from ROM", value=self.state.uxn_enabled,
                               id="opt_uxn_enabled",
                               tooltip="Run grind drives N renders from the Uxn param-sequencer "
                                       "ROM instead of a normal/series grind (issue #13)")
                yield Checkbox("Closed-loop", value=self.state.uxn_feedback,
                               id="opt_uxn_feedback",
                               tooltip="Feed each tick a byte measured from the source's own "
                                       "rhythm density, so the ROM's band choice reacts to the "
                                       "audio instead of ticking open-loop")
            with Grid(id="uxn_fields"):
                yield Label("ROM")
                yield Input(self.state.uxn_rom_path, id="uxn_rom_path",
                            placeholder="blank = vendored uxn_ctrl/paramgen.rom")
                yield Label("Ticks")
                yield Input(str(self.state.uxn_ticks), id="uxn_ticks",
                            placeholder="renders to drive (mode changes every 4)")
            with Horizontal(id="uxn_actions"):
                yield Button("Preview plan (no render)", id="uxn_preview", variant="default")
                yield Label("", id="uxn_status")
            yield RichLog(id="uxn_log", max_lines=120, wrap=True)

    def on_mount(self):
        self.border_title = "◈ 6 · uxn ROM control"
        self.border_subtitle = "issue #13 · l w s c ss m"
        self.refresh_status()

    # --- resolution + readiness ---
    def resolved_rom(self):
        """The ROM path that will actually be used — the typed one, or the vendored default."""
        from automixer.uxn_stream import DEFAULT_ROM
        return (self.state.uxn_rom_path or "").strip() or os.path.abspath(DEFAULT_ROM)

    def readiness(self):
        """``(ok, message)`` — is a ROM-driven run actually possible right now?

        Checks BOTH halves that can be missing: the ROM file and the ``uxncli`` emulator. The
        emulator is the one that bites — ``bin/`` is gitignored, so a fresh clone has a perfectly
        good ROM and no way to run it, and the old failure surface for that was a FileNotFoundError
        on tick 0 of a started run."""
        from automixer.uxn_stream import find_uxncli
        rom = self.resolved_rom()
        if not os.path.isfile(rom):
            return False, f"ROM not found: {rom}"
        try:
            cli = find_uxncli()
        except FileNotFoundError:
            return False, "uxncli not built — run uxn_ctrl/build.sh"
        return True, f"✓ {os.path.basename(rom)} · {os.path.basename(cli)}"

    def refresh_status(self):
        try:
            ok, msg = self.readiness()
        except Exception as e:                     # never let a status probe take the panel down
            ok, msg = False, f"probe failed: {e}"
        try:
            self.query_one("#uxn_status", Label).update(msg if ok else f"⚠ {msg}")
        except Exception:
            pass

    # --- edits ---
    def on_checkbox_changed(self, event):
        attr = {"opt_uxn_enabled": "uxn_enabled",
                "opt_uxn_feedback": "uxn_feedback"}.get(event.checkbox.id)
        if attr:
            setattr(self.state, attr, event.value)

    def on_input_changed(self, event):
        if event.input.id == "uxn_rom_path":
            self.state.uxn_rom_path = event.value
            self.refresh_status()
        elif event.input.id == "uxn_ticks":
            try:
                self.state.uxn_ticks = int(event.value)
            except ValueError:
                pass   # keep the last valid value; the field still shows what was typed

    def refresh_from_state(self):
        for wid, val in (("uxn_rom_path", self.state.uxn_rom_path),
                         ("uxn_ticks", str(self.state.uxn_ticks))):
            try:
                self.query_one(f"#{wid}", Input).value = val
            except Exception:
                pass
        for wid, val in (("opt_uxn_enabled", self.state.uxn_enabled),
                         ("opt_uxn_feedback", self.state.uxn_feedback)):
            try:
                self.query_one(f"#{wid}", Checkbox).value = val
            except Exception:
                pass
        self.refresh_status()

    # --- preview ---
    def on_button_pressed(self, event):
        if event.button.id == "uxn_preview":
            self.preview()

    def preview(self):
        ok, msg = self.readiness()
        if not ok:
            self._log(f"Cannot preview: {msg}")
            return
        ticks = max(1, min(int(self.state.uxn_ticks or 1), 64))
        self._log(f"— preview: {ticks} tick(s) from {os.path.basename(self.resolved_rom())} —")
        self._preview_worker(ticks)

    @work(thread=True, exclusive=True, group="uxn_preview")
    def _preview_worker(self, ticks):
        """One subprocess per tick — cheap, but N of them still shouldn't block the UI thread."""
        from automixer.uxn_stream import preview_uxn_sequence, describe_line
        closed = bool(self.state.uxn_feedback)
        cutter = getattr(self.state, "cutter", None)
        try:
            lines = preview_uxn_sequence(ticks, rom_path=self.resolved_rom(),
                                         cutter=cutter, closed_loop=closed)
        except Exception as e:
            self.app.call_from_thread(self._log, f"Preview failed: {e}")
            return
        if closed and cutter is None:
            self.app.call_from_thread(
                self._log, "(open-loop preview — closed-loop needs a loaded source to measure)")
        prev_mode = None
        for i, line in enumerate(lines):
            mode = describe_line(line).get("m")
            # Mark the tick where the ALGORITHM changes: that is the axis the 2026-07-24 ROM
            # gained, and the one a raw line-dump makes you diff by eye.
            mark = "  ← mode" if (mode and mode != prev_mode) else ""
            prev_mode = mode
            self.app.call_from_thread(self._log, f"[{i:2d}] {line}{mark}")
        self.app.call_from_thread(
            self._log, f"— plan: {len(lines)} render(s), modes: "
                       f"{' → '.join(dict.fromkeys(describe_line(l).get('m', '?') for l in lines))} —")

    def _log(self, text):
        try:
            self.query_one("#uxn_log", RichLog).write(text)
        except Exception:
            pass
