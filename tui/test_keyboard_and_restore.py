"""Keyboard-parity + crash-tolerance contracts for the App (operator 2026-07-19:
'make tui usable without a mouse' + 'let it crash, but don't lose session/data').

Every action must be reachable by key; panel-focus jumps (1-6) and global a/d/p/g work when no
text-typing widget has focus; session state is checkpointed before a grind and restored on startup."""
import os
import tempfile
import unittest
from unittest import mock

from tui.app import GrainTUI, _text_typing_target
from tui.state import SessionState, TrackSpec


class _FakeCutter:
    beats = [0, 400, 800]
    step = 400
    beat = 400
    audio_file_path = "/tmp/x.wav"


def _isolated_session():
    """Each test gets its own temp session file so the real ~/.mesh/grainneukeln-session.json
    (left by prior runs / real TUI use) cannot leak state into the test."""
    td = tempfile.mkdtemp()
    return os.path.join(td, "session.json")


class KeyboardParityTest(unittest.IsolatedAsyncioTestCase):
    """A keyboard-only operator must: (1) jump to any panel by number, (2) add/remove tracks and
    play/refresh outputs from anywhere (no mouse-click-to-focus first), (3) type letters into inputs
    without those letters triggering panel shortcuts."""

    async def test_digit_focus_jumps_each_panel(self):
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            from tui.widgets.source_panel import SourcePanel
            from tui.widgets.params_panel import ParamsPanel
            from tui.widgets.mode_panel import ModePanel
            from tui.widgets.tracks_panel import TracksPanel
            from tui.widgets.run_panel import RunPanel
            from tui.widgets.uxn_panel import UxnPanel
            from tui.widgets.output_panel import OutputPanel
            # Ctrl+6 is the Uxn panel now; Outputs moved to Ctrl+O when Uxn got its own panel
            # (2026-07-24) — a digit for every config panel, a letter for the two side panels.
            cmap = {
                "ctrl+1": SourcePanel, "ctrl+2": ParamsPanel, "ctrl+3": ModePanel,
                "ctrl+4": TracksPanel, "ctrl+5": RunPanel, "ctrl+6": UxnPanel,
                "ctrl+o": OutputPanel,
            }
            for key, cls in cmap.items():
                await pilot.press(key)
                await pilot.pause()
                # Ctrl+N descends INTO the panel (focus moves to the panel's first focusable child)
                # — that is desired: Ctrl+1 lands on the source INPUT so you can type immediately.
                target = app.query_one(cls)
                chain = []
                node = app.focused
                while node is not None:
                    chain.append(node)
                    node = node.parent
                self.assertIn(
                    target, chain,
                    f"pressing {key!r} must focus inside {cls.__name__}, "
                    f"got chain: {[type(c).__name__ for c in chain]}"
                )

    async def test_letter_shortcuts_fire_when_panel_focused(self):
        """Panel-local bindings (a/d in tracks, p/g in outputs) fire when that panel has focus.
        Workflow: Ctrl+4 jumps to tracks (focus on the DataTable) → 'a' adds a track. The panel
        owns those letters, so they don't conflict with typing in some other panel's Input."""
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            from tui.widgets.tracks_panel import TracksPanel
            await pilot.press("ctrl+4")   # jump to tracks → focus lands on DataTable
            await pilot.pause()
            initial = len(app.query_one(TracksPanel).tracks)
            await pilot.press("a")        # panel-local binding fires
            await pilot.pause()
            self.assertEqual(len(app.query_one(TracksPanel).tracks), initial + 1,
                             "pressing 'a' on the tracks panel must add a track")
            await pilot.press("d")        # panel-local binding fires
            await pilot.pause()
            self.assertEqual(len(app.query_one(TracksPanel).tracks), initial,
                             "pressing 'd' on the tracks panel must remove the selected track")

    async def test_letter_shortcuts_do_not_fire_when_other_panel_focused(self):
        """Typing 'a' in the source Input must INSERT 'a', not add a track — the panel-local binding
        only fires when its own panel (or a non-typing descendant) has focus."""
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            from textual.widgets import Input
            from tui.widgets.tracks_panel import TracksPanel
            src_input = app.query_one("#source_input", Input)
            src_input.focus()
            initial = len(app.query_one(TracksPanel).tracks)
            await pilot.press("a")
            await pilot.pause()
            self.assertEqual(len(app.query_one(TracksPanel).tracks), initial,
                             "letter 'a' in source Input must NOT add a track")
            self.assertIn("a", src_input.value, "letter 'a' must reach the source Input")

    async def test_digit_shortcuts_suppressed_when_input_focused(self):
        """Bare digits in an Input must TYPE the digit (sample_length, swing etc. take numbers).
        Ctrl+N (the panel-jump form) still fires from inside an Input — verified by the
        test_digit_focus_jumps_each_panel test which starts each jump from the prior panel's Input."""
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            from textual.widgets import Input
            from tui.widgets.source_panel import SourcePanel
            sl = app.query_one("#sample_length", Input)
            sl.focus()
            await pilot.press("1")
            await pilot.pause()
            self.assertNotIsInstance(app.focused, SourcePanel,
                                     "bare digit '1' in an Input must NOT focus the source panel")
            self.assertIn("1", sl.value, "bare digit '1' must reach the Input as a typed character")

    async def test_ctrl_l_focuses_source_input(self):
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            from textual.widgets import Input
            await pilot.press("ctrl+l")
            await pilot.pause()
            self.assertIsInstance(app.focused, Input)
            self.assertEqual(app.focused.id, "source_input")

    async def test_question_mark_opens_help(self):
        """`?` is an alias for F1 (Help) — it now pushes a scrollable modal (was a transient toast;
        a keymap + full amc grammar does not fit, or survive, a timed notification)."""
        from tui.screens import HelpScreen
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            app.action_help()
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)


class TextTypingTargetTest(unittest.TestCase):
    """The _text_typing_target predicate decides whether letter/digit shortcuts fire. It must cover
    every widget that consumes character keys — Input, Select, DataTable — and nothing else, so a
    letter reaching a non-typing widget (Static, Button, ListItem) still fires its shortcut."""

    def test_input_is_typing_target(self):
        from textual.widgets import Input
        self.assertTrue(_text_typing_target(Input()))

    def test_static_is_not_typing_target(self):
        from textual.widgets import Static
        self.assertFalse(_text_typing_target(Static()))

    def test_none_is_not_typing_target(self):
        self.assertFalse(_text_typing_target(None))


class SessionRestoreTest(unittest.IsolatedAsyncioTestCase):
    """On startup the App must restore the last checkpointed session — the params/tracks/source a
    crash or restart took away. ``cutter`` is never restored (it is the loaded audio); the source
    path is dropped into the input for the operator to press Enter on (not auto-loaded, since a
    crash during a grind of THAT source may want editing before retry)."""

    async def test_state_restored_from_session_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "session.json")
            prior = SessionState(
                speed=2.5, mode="poly", sample_length_ms=490, window_divider=6,
                tracks=[TrackSpec(80, 2000), TrackSpec(2000, 12000)],
                streams_spec="4;3", source_path="/tmp/previous.wav",
            )
            prior.save(path)
            app = GrainTUI(output_dir="output", session_path=path)
            async with app.run_test(size=(150, 40)) as pilot:
                await pilot.pause()
                self.assertEqual(app.state.speed, 2.5)
                self.assertEqual(app.state.mode, "poly")
                self.assertEqual(app.state.sample_length_ms, 490)
                self.assertEqual(app.state.window_divider, 6)
                self.assertEqual(len(app.state.tracks), 2)
                self.assertEqual(app.state.source_path, "/tmp/previous.wav")
                self.assertIsNone(app.state.cutter, "cutter must NOT be restored from disk")
                from textual.widgets import Input
                self.assertEqual(app.query_one("#source_input", Input).value,
                                 "/tmp/previous.wav",
                                 "restored source path must be pre-filled in the input")

    async def test_first_run_with_no_session_uses_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "absent.json")
            app = GrainTUI(output_dir="output", session_path=path)
            async with app.run_test(size=(150, 40)) as pilot:
                await pilot.pause()
                self.assertEqual(app.state.speed, 1.0)
                self.assertEqual(app.state.mode, "rw")

    async def test_corrupt_session_falls_back_to_defaults(self):
        """A truncated session file must not crash the TUI — fall back to defaults cleanly."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "broken.json")
            with open(path, "w") as f:
                f.write("{ broken json")
            app = GrainTUI(output_dir="output", session_path=path)
            async with app.run_test(size=(150, 40)) as pilot:
                await pilot.pause()
                self.assertEqual(app.state.mode, "rw")

    async def test_grind_checkpoints_session_before_starting(self):
        """The crash-tolerance contract: pressing Ctrl+R (action_run) saves the session BEFORE the
        grind starts, so if the grind crashes the process the params that bombed are on disk.

        Test via the Input fields (the real UI surface) — setting state.speed directly is overwritten
        by ParamsPanel.apply_to_state() reading the Input value back into state."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "session.json")
            app = GrainTUI(output_dir="output", session_path=path)
            async with app.run_test(size=(150, 40)) as pilot:
                await pilot.pause()
                # Land a source so Run is enabled.
                from tui.widgets.source_panel import SourcePanel
                cutter = _FakeCutter()
                app.query_one(SourcePanel).post_message(SourcePanel.Loaded(cutter))
                await pilot.pause()
                # Set speed via the Input — the path action_run reads back through apply_to_state.
                from textual.widgets import Input
                speed_input = app.query_one("#speed", Input)
                speed_input.value = "3.5"
                app.action_run()
                # Session file must exist immediately after action_run (before the worker finishes).
                self.assertTrue(os.path.exists(path))
                import json
                with open(path) as f:
                    d = json.load(f)
                self.assertEqual(d["speed"], 3.5)
                self.assertEqual(d["source_path"], "/tmp/x.wav")

    async def test_source_load_persists_source_path(self):
        """When a source finishes loading, its path is written to the session so a restart can
        recover it without the operator retyping."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "session.json")
            app = GrainTUI(output_dir="output", session_path=path)
            async with app.run_test(size=(150, 40)) as pilot:
                await pilot.pause()
                from tui.widgets.source_panel import SourcePanel
                cutter = _FakeCutter()
                cutter.audio_file_path = "/tmp/the-source.wav"
                app.query_one(SourcePanel).post_message(SourcePanel.Loaded(cutter))
                await pilot.pause()
                import json
                with open(path) as f:
                    d = json.load(f)
                self.assertEqual(d["source_path"], "/tmp/the-source.wav")


if __name__ == "__main__":
    unittest.main()
