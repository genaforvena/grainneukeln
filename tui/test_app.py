import os
import tempfile
import unittest
from tui.app import GrainTUI

ASSET = os.path.join(os.path.dirname(__file__), "..", "assets", "test_audio.mp3")


def _real_cutter():
    """A genuine SampleCutter (not the bare-attribute _FakeCutter below) — the Uxn seeding fix
    drives config_automix/auto_mixer_config (and asserts audio2 stays UNLOADED), none of which
    the duck-typed fake implements. Truncated post-load to a short clip, mirroring tui/test_engine.py
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
            # The stub DRIVES the on_tick callback (2026-07-24): per-tick logging and the progress
            # bar are now the callback's job, so a stub that ignores it would assert nothing about
            # the thing that actually reports progress during a long ROM run.
            def fake_sequence(cutter, ticks, on_tick=None, **kw):
                lines = ["l 100 s 1.0 m rw", "l 200 s 0.9 m rw", "l 300 s 1.1 m q"][:ticks]
                for i, line in enumerate(lines):
                    if on_tick:
                        on_tick(i, line, "start")
                        on_tick(i, line, "done")
                return lines

            with patch("automixer.uxn_stream.run_uxn_sequence",
                       side_effect=fake_sequence) as stub:
                app.query_one(RunPanel).start()
                await app.workers.wait_for_complete()
                await pilot.pause()
            stub.assert_called_once()
            btn = app.query_one("#run_btn", Button)
            self.assertFalse(btn.disabled, "Run must re-enable after a successful Uxn run")
            log_text = "\n".join(str(l) for l in app.query_one("#run_log", RichLog).lines)
            self.assertIn("[tick 3/3", log_text)
            # The mode axis is the 2026-07-24 ROM addition — the log must name which ALGORITHM
            # each tick is cutting with, not just its knobs.
            self.assertIn("m q", log_text)
            self.assertIn("3 tick(s) complete", log_text)

    async def test_uxn_seeds_env_rv_and_source2_stays_unloaded(self):
        # THE FIX under test (review findings, rounds 3+4): _run_uxn used to hand state.cutter
        # straight to run_uxn_sequence without ever routing through engine.build_config, so the
        # operator's env_pct/reverse_prob were silent no-ops in Uxn mode — cutter.config_automix's
        # token-absent fallback reads whatever is cached on cutter.auto_mixer_config, and nothing
        # wrote that cache. Round 4: Source B is structurally UNREACHABLE in Uxn mode (every ROM
        # tick's `c` token rebuilds channels_config with source2=False — see
        # UxnBandHonestyGuardTest), so the Uxn path must NOT load audio2 (dead weight that
        # manufactures the false impression it is used) and must say loudly that Source B is inert.
        # Drives the REAL seeding code against a REAL SampleCutter and asserts the cutter-side
        # state (not an injected expectation).
        from unittest.mock import patch
        from textual.widgets import RichLog
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
            # Since the ROM gained the `m` axis (2026-07-24) a run drives THROUGH q/poly/lib, so
            # those modes' own settings are exactly the ones the old env/rv-only seed dropped.
            app.query_one("#euclid_k", Input).value = "5"
            app.query_one("#euclid_n", Input).value = "16"
            app.query_one("#lib_clusters", Input).value = "9"
            app.query_one("#swing", Input).value = "66"
            app.query_one("#seed", Input).value = "1234"
            app.state.source2_path = ASSET
            with patch("automixer.uxn_stream.run_uxn_sequence",
                       return_value=["l 500 w 4"]) as stub:
                app.query_one(RunPanel).start()
                await app.workers.wait_for_complete()
                await pilot.pause()
            stub.assert_called_once()
            # Seeding must land BEFORE run_uxn_sequence ticks, so the ROM's per-tick config_automix
            # (which never emits `env`/`rv` tokens) falls back to these on EVERY tick.
            self.assertEqual(cutter.auto_mixer_config.env_pct, 22.0)
            self.assertEqual(cutter.auto_mixer_config.reverse_prob, 0.65)
            # ...and every OTHER param the ROM does not emit. Each of these was a silent no-op in
            # ROM mode before 2026-07-24: the panel showed the operator's value, the render used
            # the default. `c`/`l`/`w`/`s`/`ss`/`m` are deliberately absent — the ROM owns those.
            self.assertEqual(cutter.auto_mixer_config.euclid_k, 5)
            self.assertEqual(cutter.auto_mixer_config.euclid_n, 16)
            self.assertEqual(cutter.auto_mixer_config.lib_clusters, 9)
            self.assertEqual(cutter.auto_mixer_config.swing, 66.0)
            self.assertEqual(cutter.auto_mixer_config.seed, 1234)
            # Source B must NOT be loaded by the Uxn path: no channel can ever have source2=True
            # here (ROM owns the band string), so loading audio2 would only fake applicability.
            self.assertIsNone(getattr(cutter, "audio2", None),
                              "Uxn path must not load audio2 — Source B is unreachable in Uxn mode")
            # And the operator who set Source B must be TOLD it is inert — even with no track
            # tagged B (this test tags none), the note must fire because source2_path is set.
            log_text = "\n".join(str(l) for l in app.query_one("#run_log", RichLog).lines)
            self.assertIn("Source B", log_text)
            self.assertIn("don't apply", log_text)

    async def test_uxn_logs_once_that_rom_owns_bands_when_a_track_tags_source2(self):
        # THE FIX under test, part 2: per-track A/B tags AND Source B CANNOT compose with Uxn
        # mode (the ROM emits its own `c` band string every tick — bands are ROM-owned there),
        # so silently dropping them would be a silent no-op again. The TUI must say so, loudly,
        # once — not per tick.
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
            # Asserted in wrap-safe fragments — the RichLog word-wraps long lines across strips.
            self.assertIn("per-track A/B tags and Source B don't apply", log_text)
            self.assertIn("euclid/poly/lib/snap/swing/seed do", log_text)

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
            # Info speaks the amc grammar now — the same string the command bar takes, so what
            # `i` prints can be pasted straight back in (or into the CLI).
            self.assertIn("m q", lines)
            self.assertIn("ek 3", lines)
            self.assertIn("en 8", lines)
            self.assertIn("bands:", lines)


class UxnBandHonestyGuardTest(unittest.TestCase):
    """Structural guard for _run_uxn's honesty message (fix round 4).

    The Uxn ROM (uxn_ctrl/paramgen.tal) emits exactly one `c` band token per tick (cstr0..cstr3),
    and NONE carries a `2:` prefix — while `config_automix` rebuilds channels_config from scratch
    on every `c` token, setting source2=True only for `2:`-prefixed bands. So in Uxn mode no
    channel can ever pull from audio2, which is WHY _run_uxn does not load Source B and logs that
    it does not apply. If this test ever fails (i.e. a ROM-shaped tick line yields a
    source2=True channel), Source B has become reachable in Uxn mode: update _run_uxn's
    user-facing message (and its no-load decision) to match the new reality.
    """

    def test_rom_tick_band_string_never_selects_source2(self):
        cutter = _real_cutter()
        # A representative full ROM tick line, exactly as run_uxn_sequence feeds it
        # ("amc " + line): tokens l/w/s/c/ss, band string from paramgen.tal's cstr0.
        cutter.config_automix("amc l 200 w 4 s 0.5 c 0,0;1000,15000 ss 0.5")
        cfgs = cutter.auto_mixer_config.channels_config
        self.assertTrue(cfgs, "the ROM tick's c token must yield parsed channel configs")
        self.assertFalse(any(ch.source2 for ch in cfgs),
                         "no ROM-emitted band selects source2 — if this ever fails, Source B has "
                         "become reachable in Uxn mode and _run_uxn's message/no-load must change")
