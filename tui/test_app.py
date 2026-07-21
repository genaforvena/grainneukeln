import os
import tempfile
import unittest
from tui.app import GrainTUI

ASSET = os.path.join(os.path.dirname(__file__), "..", "assets", "test_audio.mp3")


def _real_cutter():
    """A genuine SampleCutter (not the bare-attribute _FakeCutter below) — the Uxn seeding fix
    drives config_automix/_load_secondary_audio/auto_mixer_config/audio2, none of which the
    duck-typed fake implements. Truncated post-load to a short clip, mirroring tui/test_engine.py
    and cutter/test_series_cli.py's own convention (beat-detection already ran before truncation;
    this just keeps any downstream render fast)."""
    from cutter.sample_cut_tool import SampleCutter
    c = SampleCutter(os.path.abspath(ASSET), os.path.abspath("output"))
    c.audio = c.audio[:4000]
    c.beats = c.beats[c.beats < 4000]
    return c


def _isolated_session():
    """Each test gets its own temp session file so the real ~/.mesh/grainneukeln-session.json
    (left by prior TUI runs) cannot leak state into the test — the App now restores from this file
    on startup (crash-tolerance), so unisolated tests inherit whatever the last live session set."""
    return os.path.join(tempfile.mkdtemp(), "session.json")


class _FakeCutter:
    beats = [0, 400, 800]
    step = 400
    audio_file_path = "/tmp/x.wav"

    class _FakeAMC:
        """Bare-attribute stand-in for AutoMixerConfig — enough for _run_uxn's seeding step
        (config_automix("amc env <v> rv <v>")) to have somewhere real to write."""
        env_pct = 8.0
        reverse_prob = 0.0

    def __init__(self):
        self.auto_mixer_config = self._FakeAMC()
        self.audio2 = None

    def config_automix(self, command):
        args = command.split(" ")
        if "env" in args:
            self.auto_mixer_config.env_pct = float(args[args.index("env") + 1])
        if "rv" in args:
            self.auto_mixer_config.reverse_prob = float(args[args.index("rv") + 1])

    def _load_secondary_audio(self, path):
        self.audio2 = path


class AppWiringTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_panels_fit_on_screen(self):
        # Regression: a bad `height: auto` let Source and Run each fill their whole column, pushing
        # Params/Tracks/Outputs off the bottom (y past the screen). Every panel must be visible.
        from tui.widgets.source_panel import SourcePanel
        from tui.widgets.params_panel import ParamsPanel
        from tui.widgets.tracks_panel import TracksPanel
        from tui.widgets.run_panel import RunPanel
        from tui.widgets.output_panel import OutputPanel
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            for W in (SourcePanel, ParamsPanel, TracksPanel, RunPanel, OutputPanel):
                r = app.query_one(W).region
                self.assertGreater(r.height, 0, f"{W.__name__} has zero height")
                self.assertLessEqual(r.bottom, 40, f"{W.__name__} runs off the bottom (y={r.bottom})")

    async def test_source_loaded_seeds_state(self):
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test() as pilot:
            from tui.widgets.source_panel import SourcePanel
            src = app.query_one(SourcePanel)
            src.post_message(SourcePanel.Loaded(_FakeCutter()))
            await pilot.pause()
            self.assertIsNotNone(app.state.cutter)
            self.assertEqual(app.state.sample_length_ms, 400)  # seeded from step

    async def test_tracks_changed_updates_state(self):
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test() as pilot:
            from tui.widgets.tracks_panel import TracksPanel
            panel = app.query_one(TracksPanel)
            panel.add_track()
            await pilot.pause()
            self.assertEqual(len(app.state.tracks), 2)

    async def test_run_button_gated_on_loaded_source(self):
        # The core "does not work" fix: Run is un-clickable until a source has actually loaded, so
        # "Loaded: N beats" and "No source loaded" can never disagree.
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test() as pilot:
            from textual.widgets import Button
            from tui.widgets.source_panel import SourcePanel
            btn = app.query_one("#run_btn", Button)
            self.assertTrue(btn.disabled)                       # disabled at start
            app.query_one(SourcePanel).post_message(SourcePanel.Loaded(_FakeCutter()))
            await pilot.pause()
            self.assertFalse(btn.disabled)                      # enabled once a source lands
            app.query_one(SourcePanel).post_message(SourcePanel.Failed("boom"))
            await pilot.pause()
            self.assertTrue(btn.disabled)                       # a failed reload re-locks it
            self.assertIsNone(app.state.cutter)

    async def test_real_source_worker_completion_is_not_a_grind_result(self):
        # SourcePanel's load worker is a thread worker too; its completion must NOT drive the run log
        # (the app filters on worker group == "grind").
        loaded = _FakeCutter()
        app = GrainTUI(output_dir="output", session_path=_isolated_session(), loader=lambda v: loaded, player=lambda p: None)
        async with app.run_test() as pilot:
            from textual.widgets import RichLog
            from tui.widgets.source_panel import SourcePanel
            app.query_one(SourcePanel).load("/tmp/x.wav")
            await app.workers.wait_for_complete()
            await pilot.pause()
            log_text = "\n".join(str(l) for l in app.query_one("#run_log", RichLog).lines)
            self.assertNotIn("Done", log_text)                  # no phantom "Done: <cutter>"
            self.assertIsNotNone(app.state.cutter)

    async def test_self_feed_reloads_exported_mix_as_source(self):
        # `aminf` parity: with self-feed on, a finished grind reloads the exported mp3 as the
        # source — the creative loop where each grind feeds the next.
        reloaded_paths = []
        first_cutter = _FakeCutter()
        second_cutter = _FakeCutter()
        second_cutter.audio_file_path = "/tmp/grind.mp3"
        def fake_loader(value, on_stage=None):
            reloaded_paths.append(value)
            return second_cutter if value.endswith(".mp3") else first_cutter
        app = GrainTUI(output_dir="output", session_path=_isolated_session(), loader=fake_loader, player=lambda p: None)
        async with app.run_test() as pilot:
            from tui.widgets.source_panel import SourcePanel
            from tui.widgets.run_panel import RunPanel
            # Land the initial source, then flip self-feed on.
            app.query_one(SourcePanel).post_message(SourcePanel.Loaded(first_cutter))
            await pilot.pause()
            app.state.self_feed = True
            # Simulate a finished grind → should drive a reload of the exported path. Pump the
            # Finished message FIRST so on_run_panel_finished runs and starts the reload worker
            # before we await it — otherwise wait_for_complete() sees no worker and returns before
            # the Loaded(second_cutter) cascade has a chance to swap state.cutter.
            app.query_one(RunPanel).post_message(RunPanel.Finished("/tmp/grind.mp3"))
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIn("/tmp/grind.mp3", reloaded_paths)
            self.assertIs(app.state.cutter, second_cutter)   # cutter actually swapped

    async def test_self_feed_off_does_not_reload(self):
        first_cutter = _FakeCutter()
        reloaded_paths = []
        def fake_loader(value, on_stage=None):
            reloaded_paths.append(value)
            return first_cutter
        app = GrainTUI(output_dir="output", session_path=_isolated_session(), loader=fake_loader, player=lambda p: None)
        async with app.run_test() as pilot:
            from tui.widgets.source_panel import SourcePanel
            from tui.widgets.run_panel import RunPanel
            app.query_one(SourcePanel).post_message(SourcePanel.Loaded(first_cutter))
            await pilot.pause()
            app.query_one(RunPanel).post_message(RunPanel.Finished("/tmp/out.mp3"))
            await pilot.pause()
            self.assertEqual(reloaded_paths, [])   # no reload when self-feed is off

    async def test_uxn_worker_completion_reenables_run(self):
        # Regression: the Uxn work() returns None (its renders have no single "last path"), and
        # on_worker_state_changed only fires _on_finished on a TRUTHY result — so after a real
        # successful Uxn run nothing re-enabled the Run button and the operator had to restart
        # the TUI. Completion now happens inside the worker via _uxn_finished. This drives the
        # REAL threaded-worker path (no injected sync runner).
        from unittest.mock import patch
        from textual.widgets import Button, RichLog
        app = GrainTUI(output_dir=tempfile.mkdtemp(), session_path=_isolated_session())
        async with app.run_test() as pilot:
            from tui.widgets.source_panel import SourcePanel
            from tui.widgets.run_panel import RunPanel
            app.query_one(SourcePanel).post_message(SourcePanel.Loaded(_FakeCutter()))
            await pilot.pause()
            app.state.uxn_enabled = True
            app.state.uxn_ticks = 3
            with patch("automixer.uxn_stream.run_uxn_sequence",
                       return_value=["l=100 s=1.0", "l=200 s=0.9", "l=300 s=1.1"]) as stub:
                app.query_one(RunPanel).start()
                await app.workers.wait_for_complete()
                await pilot.pause()
            stub.assert_called_once()
            btn = app.query_one("#run_btn", Button)
            self.assertFalse(btn.disabled, "Run must re-enable after a successful Uxn run")
            log_text = "\n".join(str(l) for l in app.query_one("#run_log", RichLog).lines)
            self.assertIn("[uxn tick 2]", log_text)
            self.assertIn("3 tick(s) complete", log_text)

    async def test_uxn_seeds_env_rv_and_source2_onto_cutter(self):
        # THE FIX under test (review finding): _run_uxn used to hand state.cutter straight to
        # run_uxn_sequence without ever routing through engine.build_config, so the operator's
        # env_pct/reverse_prob/Source B were silent no-ops in Uxn mode — cutter.config_automix's
        # token-absent fallback reads whatever is cached on cutter.auto_mixer_config/cutter.audio2,
        # and nothing wrote those caches. Drives the REAL seeding code against a REAL SampleCutter
        # and asserts the cutter-side state the seeding wrote (not an injected expectation).
        from unittest.mock import patch
        cutter = _real_cutter()
        app = GrainTUI(output_dir=tempfile.mkdtemp(), session_path=_isolated_session())
        async with app.run_test() as pilot:
            from textual.widgets import Input
            from tui.widgets.source_panel import SourcePanel
            from tui.widgets.run_panel import RunPanel
            app.query_one(SourcePanel).post_message(SourcePanel.Loaded(cutter))
            await pilot.pause()
            app.state.uxn_enabled = True
            app.state.uxn_ticks = 2
            # _threaded_runner calls ParamsPanel.apply_to_state() before dispatching to _run_uxn,
            # which OVERWRITES state.env_pct/reverse_prob from the panel's live Input widgets — so
            # the operator-facing seam under test is the widget value, not a direct state poke.
            app.query_one("#env_pct", Input).value = "22.0"
            app.query_one("#reverse_prob", Input).value = "0.65"
            app.state.source2_path = ASSET
            with patch("automixer.uxn_stream.run_uxn_sequence",
                       return_value=["l 500 w 4"]) as stub:
                app.query_one(RunPanel).start()
                await app.workers.wait_for_complete()
                await pilot.pause()
            stub.assert_called_once()
            # Seeding must land BEFORE run_uxn_sequence ticks, so the ROM's per-tick config_automix
            # (which never emits `env`/`rv`/`src2` tokens) falls back to these on EVERY tick.
            self.assertEqual(cutter.auto_mixer_config.env_pct, 22.0)
            self.assertEqual(cutter.auto_mixer_config.reverse_prob, 0.65)
            self.assertIsNotNone(cutter.audio2)

    async def test_uxn_logs_once_that_rom_owns_bands_when_a_track_tags_source2(self):
        # THE FIX under test, part 2: per-track A/B tags CANNOT compose with Uxn mode (the ROM
        # emits its own `c` band string every tick — bands are ROM-owned there), so silently
        # dropping the tag would be a silent no-op again. The TUI must say so, loudly, once — not
        # per tick.
        from unittest.mock import patch
        from textual.widgets import RichLog
        cutter = _real_cutter()
        app = GrainTUI(output_dir=tempfile.mkdtemp(), session_path=_isolated_session())
        async with app.run_test() as pilot:
            from tui.widgets.source_panel import SourcePanel
            from tui.widgets.run_panel import RunPanel
            app.query_one(SourcePanel).post_message(SourcePanel.Loaded(cutter))
            await pilot.pause()
            app.state.uxn_enabled = True
            app.state.uxn_ticks = 3
            app.state.tracks[0].source2 = True
            with patch("automixer.uxn_stream.run_uxn_sequence",
                       return_value=["l 500 w 4", "l 600 w 2", "l 700 w 8"]):
                app.query_one(RunPanel).start()
                await app.workers.wait_for_complete()
                await pilot.pause()
            log_text = "\n".join(str(l) for l in app.query_one("#run_log", RichLog).lines)
            self.assertEqual(log_text.count("ROM owns the bands"), 1,
                              "the note must be logged exactly once, not per tick")

    async def test_info_dumps_config_to_run_log(self):
        # `amc info` + `info` parity: pressing `i` writes the live source + grind config to the log.
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test() as pilot:
            from textual.widgets import RichLog
            from tui.widgets.source_panel import SourcePanel
            app.query_one(SourcePanel).post_message(SourcePanel.Loaded(_FakeCutter()))
            await pilot.pause()
            app.state.mode = "q"
            app.state.euclid_k = 3
            app.state.euclid_n = 8
            app.action_info()
            await pilot.pause()
            lines = "\n".join(str(l) for l in app.query_one("#run_log", RichLog).lines)
            self.assertIn("Source:", lines)
            self.assertIn("mode=q", lines)
            self.assertIn("E(3,8)", lines)
