import os
import tempfile
import unittest
from textual.app import App, ComposeResult
from tui.widgets.output_panel import OutputPanel
from tui.player import DummyPlayer, PlaybackState


class _Host(App):
    def __init__(self, d, player):
        super().__init__()
        self._d = d
        self._player = player

    def compose(self) -> ComposeResult:
        yield OutputPanel(self._d, self._player)


def _touch(d, name):
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(b"\x00" * 10)
    return p


class OutputPanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_lists_files(self):
        with tempfile.TemporaryDirectory() as d:
            _touch(d, "a.mp3")
            _touch(d, "b.mp3")
            app = _Host(d, DummyPlayer())
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                await pilot.pause()
                self.assertEqual(len(panel.paths), 2)

    async def test_space_starts_playback_when_stopped(self):
        """space = play (the primary key) — operator 2026-07-19: 'playback should be possible to start'."""
        with tempfile.TemporaryDirectory() as d:
            _touch(d, "a.mp3")
            player = DummyPlayer()
            app = _Host(d, player)
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                await pilot.pause()
                panel.focus()
                await pilot.pause()
                await pilot.press("space")
                await pilot.pause()
                self.assertEqual(player.state()["state"], PlaybackState.PLAYING)
                self.assertTrue(player.state()["path"].endswith(".mp3"))

    async def test_space_pauses_when_playing(self):
        """space toggles — a second press pauses. Pause keeps position so resume continues here."""
        with tempfile.TemporaryDirectory() as d:
            _touch(d, "a.mp3")
            player = DummyPlayer()
            app = _Host(d, player)
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                panel.focus()
                await pilot.pause()
                await pilot.press("space")
                await pilot.pause()
                self.assertEqual(player.state()["state"], PlaybackState.PLAYING)
                await pilot.press("space")
                await pilot.pause()
                self.assertEqual(player.state()["state"], PlaybackState.PAUSED)

    async def test_space_resumes_when_paused(self):
        """Third space (after play→pause) resumes — the one key covers start/pause/resume."""
        with tempfile.TemporaryDirectory() as d:
            _touch(d, "a.mp3")
            player = DummyPlayer()
            app = _Host(d, player)
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                panel.focus()
                await pilot.pause()
                await pilot.press("space")     # play
                await pilot.press("space")     # pause
                await pilot.pause()
                await pilot.press("space")     # resume
                await pilot.pause()
                self.assertEqual(player.state()["state"], PlaybackState.PLAYING)

    async def test_s_stops_playback(self):
        """s = stop (reset position to 0). Distinguished from pause: stop forgets where it was."""
        with tempfile.TemporaryDirectory() as d:
            _touch(d, "a.mp3")
            player = DummyPlayer()
            app = _Host(d, player)
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                panel.focus()
                await pilot.pause()
                await pilot.press("space")
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()
                self.assertEqual(player.state()["state"], PlaybackState.STOPPED)

    async def test_dot_seeks_forward_comma_seeks_back(self):
        """`.` ff 10s, `,` back 10s — the seek contract. Position must move accordingly."""
        with tempfile.TemporaryDirectory() as d:
            _touch(d, "a.mp3")
            player = DummyPlayer()
            app = _Host(d, player)
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                panel.focus()
                await pilot.pause()
                await pilot.press("space")
                await pilot.pause()
                pos_before = player.state()["pos_sec"]
                await pilot.press("dot")      # ff 10s
                await pilot.pause()
                pos_after_ff = player.state()["pos_sec"]
                self.assertGreater(pos_after_ff, pos_before,
                                   "ff seek must advance the position")
                await pilot.press("comma")    # back 10s
                await pilot.pause()
                pos_after_back = player.state()["pos_sec"]
                self.assertLess(pos_after_back, pos_after_ff,
                                "back seek must retreat the position")

    async def test_seek_clamps_at_zero(self):
        """Backwards past the start clamps to 0 — never negative."""
        with tempfile.TemporaryDirectory() as d:
            _touch(d, "a.mp3")
            player = DummyPlayer()
            app = _Host(d, player)
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                panel.focus()
                await pilot.pause()
                await pilot.press("space")
                await pilot.pause()
                await pilot.press("comma")    # back 10s from ~0
                await pilot.pause()
                self.assertGreaterEqual(player.state()["pos_sec"], 0.0)

    async def test_status_line_updates_with_playback_state(self):
        """The status label above the list reflects ▶/⏸/⏹ — the operator reads playback state at a
        glance. Verified via the status text the label holds, not a UI render (Textual's Label
        internals vary across versions; the _status_text() producer is the stable surface)."""
        with tempfile.TemporaryDirectory() as d:
            _touch(d, "a.mp3")
            player = DummyPlayer()
            app = _Host(d, player)
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                panel.focus()
                await pilot.pause()
                # Stopped: ⏹ icon, no position
                self.assertIn("⏹", panel._status_text())
                await pilot.press("space")
                await pilot.pause()
                panel._refresh_status()
                # Playing: ▶ icon with a position number
                self.assertIn("▶", panel._status_text())
                await pilot.press("space")   # pause
                await pilot.pause()
                panel._refresh_status()
                self.assertIn("⏸", panel._status_text())


class OutputPanelCapTest(unittest.IsolatedAsyncioTestCase):
    """The list is capped to the newest ``MAX_LIST`` renders. The output dir grows without bound
    (the grinder never prunes it — 1000+ files in practice), and mounting one widget per file made
    both real TUI startup and every app-level test take 5–12 s just to build the panel."""

    async def test_caps_to_newest_and_announces_the_rest(self):
        import time
        with tempfile.TemporaryDirectory() as d:
            n = OutputPanel.MAX_LIST + 25
            # Distinct mtimes so "newest N" is well-defined; older files get older mtimes.
            base = time.time() - n
            for i in range(n):
                p = _touch(d, f"grain_{i:04d}.mp3")
                os.utime(p, (base + i, base + i))     # file i is newer than file i-1
            app = _Host(d, DummyPlayer())
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                await pilot.pause()
                # Exactly MAX_LIST playable paths — the surplus is NOT in the selectable set.
                self.assertEqual(len(panel.paths), OutputPanel.MAX_LIST)
                # The ones kept are the newest (highest index in our naming), newest-first.
                self.assertTrue(panel.paths[0].endswith(f"grain_{n - 1:04d}.mp3"))
                self.assertTrue(all(f"grain_{n - 1 - i:04d}.mp3" in panel.paths[i]
                                    for i in range(5)))
                # The cut is LOUD: a trailing hint row exists for the hidden remainder.
                from textual.widgets import ListView
                lv = panel.query_one("#output_list", ListView)
                self.assertEqual(len(lv.children), OutputPanel.MAX_LIST + 1)

    async def test_no_hint_row_when_under_cap(self):
        with tempfile.TemporaryDirectory() as d:
            _touch(d, "a.mp3")
            _touch(d, "b.mp3")
            app = _Host(d, DummyPlayer())
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                await pilot.pause()
                from textual.widgets import ListView
                lv = panel.query_one("#output_list", ListView)
                self.assertEqual(len(lv.children), 2)   # no extra "… older" row


class OutputPanelLegacyCallableTest(unittest.IsolatedAsyncioTestCase):
    """Back-compat: existing tests inject a ``player(path)`` callable (no pause/seek). The panel
    must still work with these — space plays, the legacy callable fires once per play."""

    async def test_space_plays_via_legacy_callable(self):
        with tempfile.TemporaryDirectory() as d:
            _touch(d, "a.mp3")
            played = []
            app = _Host(d, lambda p: played.append(p))
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                panel.focus()
                await pilot.pause()
                await pilot.press("space")
                await pilot.pause()
                self.assertEqual(len(played), 1)
                self.assertTrue(played[0].endswith(".mp3"))

    async def test_legacy_playable_failure_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            _touch(d, "a.mp3")

            def no_sink(path):
                raise RuntimeError("no audio device")

            app = _Host(d, no_sink)
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                await pilot.pause()
                panel.play_selected()      # must not raise
                await pilot.pause()
                self.assertEqual(len(panel.paths), 1)   # TUI still alive


if __name__ == "__main__":
    unittest.main()
