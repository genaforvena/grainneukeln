import os
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Input, Select, DataTable

from tui.state import SessionState, SESSION_PATH, CRASH_LOG
from tui import engine
from tui.amc import format_amc
from tui.player import make_player
from tui.screens import CrashScreen, HelpScreen
from tui.theme import grain_theme
from tui.widgets.banner import Banner
from tui.widgets.command_bar import CommandBar
from tui.widgets.source_panel import SourcePanel
from tui.widgets.params_panel import ParamsPanel
from tui.widgets.mode_panel import ModePanel
from tui.widgets.tracks_panel import TracksPanel
from tui.widgets.run_panel import RunPanel
from tui.widgets.uxn_panel import UxnPanel
from tui.widgets.output_panel import OutputPanel


def _real_loader(value, on_stage=None, low_memory=False):
    """Download (if a URL) + build a SampleCutter. Runs on SourcePanel's worker thread, so the
    slow parts (yt-dlp download, librosa beat-detection) never freeze the UI. on_stage(str) streams
    human progress to the source status line."""
    def stage(text):
        if on_stage:
            on_stage(text)

    from cutter.sample_cut_tool import SampleCutter
    out = os.path.abspath("output")
    os.makedirs(out, exist_ok=True)
    if value.startswith("http://") or value.startswith("https://"):
        import youtube.downloader as downloader
        stage("Downloading from YouTube… 0%")
        value = downloader.download_video(
            value, out, progress_callback=lambda pct: stage(f"Downloading from YouTube… {pct}%"))
        stage(f"Downloaded → {os.path.relpath(value, out)}. Detecting beats (librosa)…")
    else:
        value = os.path.abspath(value)
        stage("Detecting beats (librosa)…")
    return SampleCutter(value, out, low_memory=low_memory)


def _real_player(path):
    from pydub import AudioSegment
    import pydub.playback
    pydub.playback.play(AudioSegment.from_file(path))


def _text_typing_target(focused):
    """True when the currently-focused widget would CONSUME a letter key — so panel shortcuts (a/d/p/g,
    digits 1-6) must NOT fire. Binding them at app level would otherwise fire while the operator is
    typing 'audio.wav' into the source box ('a' = add track would fire on every 'a')."""
    return isinstance(focused, (Input, Select, DataTable))


class GrainTUI(App):
    CSS_PATH = "app.tcss"
    # The Footer shows every binding here, so the operator can read the whole keymap without a manual.
    # Design: Ctrl-prefixed keys ALWAYS fire (panel jumps, run, crash-log) — they're the navigation
    # backbone the operator can rely on regardless of where the cursor is. Bare-letter shortcuts
    # (a/d/t/b in tracks, space/s/g in outputs) are panel-LOCAL — they fire only when that panel has
    # focus, so typing 'a' in the source path inserts 'a' rather than adding a track. Help (?) lists
    # the full keymap.
    BINDINGS = [
        ("ctrl+r", "run", "Run grind"),
        ("ctrl+e", "focus_amc", "amc bar"),
        ("ctrl+l", "focus_source", "Focus source"),
        Binding("ctrl+1", "focus_panel('1')", "Source", show=False),
        Binding("ctrl+2", "focus_panel('2')", "Params", show=False),
        Binding("ctrl+3", "focus_panel('3')", "Mixer", show=False),
        Binding("ctrl+4", "focus_panel('4')", "Bands", show=False),
        Binding("ctrl+5", "focus_panel('5')", "Run", show=False),
        Binding("ctrl+6", "focus_panel('6')", "Uxn", show=False),
        Binding("ctrl+o", "focus_panel('o')", "Outputs", show=False),
        ("i", "info", "Info"),
        ("f1,question", "help", "Help"),
        ("ctrl+t", "open_crash_log", "Crash log"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, output_dir="output", loader=None, player=None, low_memory=False,
                 session_path=SESSION_PATH, initial_state=None, autoload=None):
        super().__init__()
        # Restore the last session BEFORE the panels compose — they read state to seed themselves.
        # None on first run (no prior session); a previous SessionState on restart-after-crash.
        prior = SessionState.load(session_path)
        if initial_state is not None:
            # A caller (main.py's CLI flags) handed us an explicit state — it WINS over the restored
            # session, because flags typed just now are a newer statement of intent than a file.
            self.state = initial_state
            self.state.output_dir = output_dir or initial_state.output_dir
        elif prior is not None:
            # cutter is not serialized — re-load from source_path lazily (the user re-presses Enter
            # or the load is auto-triggered on mount). Output_dir from prior if set, else caller's.
            self.state = prior
            self.state.cutter = None
            self.state.output_dir = output_dir or prior.output_dir
        else:
            self.state = SessionState(output_dir=output_dir)
        if low_memory:
            self.state.low_memory = True
        self._loader = loader or _real_loader
        # Player: a Player instance (preferred — supports start/stop/pause/seek) or a legacy
        # ``player(path)`` callable (existing tests inject these). Default: pick the best for the node.
        self._player = player if player is not None else make_player()
        self.low_memory = low_memory
        self._session_path = session_path
        # A source to load the moment the UI is up (``main.py song.mp3 out/ --tui``). Before
        # 2026-07-24 the positional args were parsed and then silently dropped for --tui, so the
        # operator watched an empty Source box after naming a file on the command line.
        self._autoload = autoload

    def compose(self) -> ComposeResult:
        yield Banner()
        with Horizontal(id="top"):
            with Vertical(id="col_left"):
                yield SourcePanel(self._loader, state=self.state)
                yield ParamsPanel(self.state)
            with Vertical(id="col_mid"):
                yield ModePanel(self.state)
                yield TracksPanel(self.state.tracks)
            with Vertical(id="col_right"):
                yield RunPanel(self.state, self._threaded_runner)
                yield UxnPanel(self.state)
                yield OutputPanel(self.state.output_dir, self._player)
        yield CommandBar(self.state)
        yield Footer()

    def on_mount(self):
        self.register_theme(grain_theme)
        self.theme = "grain"
        self.title = "grainneukeln"
        self.sub_title = "granular grinder"
        self.query_one(ParamsPanel).border_title = "◈ 2 · grind params"
        self.query_one(ParamsPanel).border_subtitle = "length · speed · grain shape · seed"
        self.query_one(ModePanel).border_title = "◈ 3 · mixer & effects"
        self.query_one(ModePanel).border_subtitle = "mode · euclid · poly · lib · snap · swing"
        self.query_one(OutputPanel).border_title = "♫ outputs · ctrl+o"
        # If the restored session had a source, drop it into the source input so the operator can
        # press Enter to reload (or it auto-loads). Don't silently re-load — a crashed session may
        # have crashed BECAUSE of that source's grind, and the operator chooses whether to retry.
        if self.state.source_path:
            try:
                self.query_one("#source_input", Input).value = self.state.source_path
            except Exception:
                pass
        self.refresh_recipe()
        if self._autoload:
            # An EXPLICIT command-line source is different from a restored one: the operator just
            # named it, so loading it without a second keystroke is what they asked for.
            self.query_one(SourcePanel).load(self._autoload)

    def on_unmount(self):
        # Final checkpoint on exit — captures any state changes after the last save. Best-effort.
        self._save_session()
        # Stop playback on exit so ffplay isn't orphaned after the TUI closes (operator 2026-07-19:
        # 'playback should be possible to start/stop' — closing the app is an implicit stop).
        if self._player is not None and hasattr(self._player, "stop"):
            try:
                self._player.stop()
            except Exception:
                pass

    def _save_session(self):
        """Snapshot the live state to disk so a subsequent crash never loses it. Called before the
        grind (so the params that bombed are persisted), on unmount (final exit state), and could
        be wired to a periodic timer. Source_path is captured from the cutter if loaded."""
        if getattr(self.state, "cutter", None) is not None:
            path = getattr(self.state.cutter, "audio_file_path", "")
            if path:
                self.state.source_path = path
        self.state.save(self._session_path)

    def refresh_recipe(self):
        """Repaint the live amc recipe line. Called after any edit that could change what Run does,
        so the line is never a stale claim."""
        try:
            self.query_one(CommandBar).refresh_recipe()
        except Exception:
            pass

    def refresh_panels_from_state(self):
        """Push the state back into every widget — the amc bar's other half.

        A typed recipe that changed what Run renders while the panels kept showing the old numbers
        would be two surfaces disagreeing about one fact: the same shape as the Loaded/No-source
        race this TUI was built to make impossible."""
        for cls in (SourcePanel, ParamsPanel, ModePanel, RunPanel, UxnPanel):
            try:
                self.query_one(cls).refresh_from_state()
            except Exception:
                pass
        try:
            self.query_one(TracksPanel).set_tracks(self.state.tracks)
        except Exception:
            pass
        self.refresh_recipe()

    # --- wiring ---
    def on_command_bar_applied(self, msg):
        if msg.series:
            self.notify(f"Series armed: {msg.series}", title="amc", timeout=6)
            self.refresh_panels_from_state()
            return
        if msg.errors:
            self.notify("\n".join(msg.errors), severity="error", title="amc", timeout=10)
        self.refresh_panels_from_state()
        self._save_session()

    def on_source_panel_loading(self, msg):
        self.state.cutter = None
        self.query_one(RunPanel).set_ready(False, "loading source…")

    def on_source_panel_failed(self, msg):
        self.state.cutter = None
        self.query_one(RunPanel).set_ready(False, "load a source first")

    def on_source_panel_loaded(self, msg):
        self.state.cutter = msg.cutter
        # Remember the path so a crash-restart can re-load the same source — the operator does not
        # retype it. ``audio_file_path`` is the absolute path the cutter holds post-load (for a
        # YouTube URL it is the downloaded file's path, not the original URL — still reloadable).
        self.state.source_path = getattr(msg.cutter, "audio_file_path", self.state.source_path or "")
        # Seed the grind length from the real beat period (the base for /2 /3 *2). Fall back to the
        # navigation step only when the beat is unknowable (< 2 beats detected).
        beat = int(getattr(msg.cutter, "beat", 0) or 0)
        base = beat if beat > 0 else int(getattr(msg.cutter, "step", 0) or 0)
        params = self.query_one(ParamsPanel)
        params.set_beat(beat)
        if base > 0:
            self.state.sample_length_ms = base
            try:
                self.query_one("#sample_length", Input).value = str(base)
            except Exception:
                pass
        self.query_one(RunPanel).set_ready(True)
        self.refresh_recipe()
        self._save_session()

    def on_tracks_panel_changed(self, msg):
        self.state.tracks = msg.tracks
        self.refresh_recipe()
        self._save_session()

    def on_run_panel_finished(self, msg):
        self.query_one(OutputPanel).refresh_list()
        if self.state.self_feed:
            self._self_feed_from(msg.path)

    def _self_feed_from(self, path):
        """Reload the just-exported mp3 as the source — the `aminf` creative loop: each grind
        becomes the input to the next. Runs on the same threaded loader the SourcePanel uses so
        the UI stays responsive, and posts the same Loaded/Failed messages so all the readiness
        wiring (Run button gate, beat seed) updates exactly as if the operator typed the path."""
        panel = self.query_one(RunPanel)
        panel._log(f"Self-feed → reloading {os.path.basename(path)} as source…")
        src = self.query_one(SourcePanel)
        src.load(path)

    def action_info(self):
        """`amc info` + `info` parity: dump the live source + grind config into the run log so the
        operator can read what is about to render without leaving the TUI."""
        panel = self.query_one(RunPanel)
        s = self.state
        cutter = s.cutter
        if cutter is None:
            panel._log("Info: no source loaded")
            return
        beats = getattr(cutter, "beats", None)
        n_beats = len(beats) if beats is not None else 0
        beat = int(getattr(cutter, "beat", 0) or 0)
        path = getattr(cutter, "audio_file_path", "?")
        n_filtered = sum(0 if t.bypass else 1 for t in s.tracks)
        panel._log(
            f"Source: {os.path.basename(path)} · {n_beats} beats · beat={beat}ms\n"
            f"  {format_amc(s)}\n"
            f"  bands: {len(s.tracks)} ({n_filtered} filtered / {len(s.tracks) - n_filtered} raw)"
            f" · out: wav={'on' if s.wav_export else 'off'}"
            f" verbose={'on' if s.verbose else 'off'}"
            f" self-feed={'on' if s.self_feed else 'off'}"
            f" low-mem={'on' if s.low_memory else 'off'}"
        )

    def action_run(self):
        errs = self.query_one(ParamsPanel).apply_to_state()
        errs += self.query_one(ModePanel).apply_to_state()
        if errs:
            self.notify("\n".join(errs), severity="error", title="Fix params", timeout=8)
            return
        # Checkpoint BEFORE the grind starts — if it crashes the TUI (OOM/segfault), the recipe that
        # bombed is already on disk and the next launch restores it. The engine ALSO appends to the
        # crash log inside its own try/except, so we get BOTH: restored session + a crash entry.
        self._save_session()
        self.refresh_recipe()
        self.query_one(RunPanel).start()

    def action_help(self):
        self.push_screen(HelpScreen())

    def action_focus_amc(self):
        """Ctrl+E: jump to the amc command bar — the CLI's whole grammar, one keystroke away."""
        try:
            self.query_one("#amc_input", Input).focus()
        except Exception:
            pass

    def action_focus_source(self):
        """Ctrl+L: jump straight to the source input and select-all so a new path overwrites."""
        try:
            inp = self.query_one("#source_input", Input)
            self.set_focus(inp)
            inp.focus()
        except Exception:
            pass

    def action_focus_panel(self, which):
        """Ctrl+1..6 / Ctrl+O: jump to each panel. Always fires (Ctrl-prefixed — does not conflict
        with typing digits into Inputs).

        Panels extend Static and have ``can_focus=False`` — calling ``.focus()`` on the panel itself
        does nothing. We walk descendants and focus the FIRST focusable child (Input/Select/DataTable/
        Button/Checkbox/ListView), so Ctrl+2 lands on the speed Input inside ParamsPanel, and Ctrl+4
        lands on the tracks DataTable (so 'a'/'d' panel-local bindings work right after the jump)."""
        cmap = {
            "1": SourcePanel, "2": ParamsPanel, "3": ModePanel,
            "4": TracksPanel, "5": RunPanel, "6": UxnPanel, "o": OutputPanel,
        }
        cls = cmap.get(which)
        if not cls:
            return
        try:
            panel = self.query_one(cls)
        except Exception:
            return
        from textual.widgets import Input, Select, DataTable, Button, Checkbox, ListView
        focusable_types = (Input, Select, DataTable, Button, Checkbox, ListView)
        for desc in panel.walk_children(with_self=False):
            if isinstance(desc, focusable_types) and getattr(desc, "focusable", True) and not desc.disabled:
                desc.focus()
                return
        panel.focus()

    def action_add_track(self):
        """Kept as a no-op shim — track add/remove is via the TracksPanel's local bindings
        ('a'/'d') which fire when TracksPanel has focus (Ctrl+4 to jump there). The global letter
        bindings were removed because they fired at startup while the source Input had focus."""
        self.query_one(TracksPanel).add_track()

    def action_remove_track(self):
        self.query_one(TracksPanel).remove_selected()

    def action_play_output(self):
        self.query_one(OutputPanel).play_selected()

    def action_refresh_outputs(self):
        self.query_one(OutputPanel).refresh_list()

    def action_open_crash_log(self):
        """Ctrl+T: surface the last crash record so the operator reads WHAT bombed without leaving
        the TUI. The log is append-only — show the last entry (the most recent crash), WHOLE: a
        traceback truncated to a toast's 1500 chars threw away its own tail, which is the raise
        site, i.e. the part you open a crash log to read."""
        try:
            with open(CRASH_LOG) as f:
                text = f.read()
        except (OSError, FileNotFoundError):
            self.notify(f"No crash log yet ({CRASH_LOG} absent) — clean record.", timeout=6)
            return
        if not text.strip():
            self.notify("Crash log is empty — clean record.", timeout=6)
            return
        # Split on the "[stamp] CRASH" header and take the last block.
        blocks = [b for b in text.split("\n[") if "CRASH" in b]
        last = ("[" + blocks[-1]) if blocks else text
        self.push_screen(CrashScreen(last.strip()))

    # --- real threaded runner injected into RunPanel ---
    def _threaded_runner(self, state, on_progress, on_log):
        self.query_one(ParamsPanel).apply_to_state()
        self.query_one(ModePanel).apply_to_state()

        if state.uxn_enabled:
            return self._run_uxn(state, on_progress, on_log)
        spec = (state.series_spec or "").strip()
        if spec:
            return self._run_series(state, spec, on_progress, on_log)
        return self._run_single(state, on_progress, on_log)

    def _uxn_preseed_line(self, state):
        """The amc line that seeds everything the ROM does NOT emit.

        The ROM's per-tick line carries only ``l w s c ss m``, and ``config_automix`` overrides only
        the fields whose tokens are present — everything else falls back to whatever is cached on
        ``cutter.auto_mixer_config``. Nothing wrote those caches, so the TUI's own panel settings
        were silent no-ops in ROM mode. The 2026-07-21 fix seeded env/rv only; since the ROM gained
        the ``m`` axis (2026-07-24) it now drives runs THROUGH q/poly/lib, whose settings —
        euclid k/n, gap-fill, the poly stream spec, the lib policy and cluster count — were exactly
        the ones still being dropped. Seed all of them, plus snap/swing/seed, in one call before the
        tick loop; each tick's token-absent fallback then picks them up for the whole run.

        Deliberately NOT seeded: ``c`` (the ROM writes a band string every tick, so a seeded one is
        overwritten on tick 0 and would be a lie in the recipe) and ``l w s ss m`` (same). Source B
        cannot compose either — see ``_run_uxn``."""
        s = state
        parts = [f"env {s.env_pct:g}", f"rv {s.reverse_prob:g}",
                 f"ek {s.euclid_k}", f"en {s.euclid_n}",
                 f"lib {'con' if s.lib_policy == 'contrast' else 'sim'}", f"lk {s.lib_clusters}",
                 f"sw {s.swing:g}", f"fg {s.fill_gain_db:g}"]
        if s.snap:
            parts.append("snap")
        if not s.fill:
            parts.append("nofill")
        if s.streams_spec:
            parts.append(f"pr {s.streams_spec}")
        seed = s.amc_seed()
        if seed is not None:
            parts.append(f"seed {seed}")
        return "amc " + " ".join(parts)

    def _run_uxn(self, state, on_progress, on_log):
        """Drive renders from the Uxn param-sequencer ROM (issue #13), on the same worker-thread
        pattern as ``_run_single``/``_run_series``.

        Per-track A/B tags AND Source B CANNOT compose with this mode — the ROM emits its own `c`
        band string every tick (paramgen.tal's cstr0..cstr3, none `2:`-prefixed), and
        ``config_automix`` rebuilds channels_config from scratch on every `c` token with
        source2=True only for `2:`-prefixed bands, so no channel can ever pull from audio2 here
        (structural guard: test_app.py::UxnBandHonestyGuardTest). We therefore do NOT load Source B
        (loading it would be dead weight faking applicability) and say so loudly, once, instead of
        silently dropping it."""
        from automixer.uxn_stream import run_uxn_sequence, DEFAULT_ROM, describe_line

        rom = state.uxn_rom_path.strip() or DEFAULT_ROM
        ticks = max(1, int(state.uxn_ticks))
        # The output toggles are cutter-level in this path (run_uxn_sequence drives the cutter's own
        # automix/_save_mix), not engine-level — so mirror them onto the cutter or the WAV/verbose
        # checkboxes are dead in ROM mode while looking live in the panel.
        cutter = state.cutter

        def log(text):
            self.call_from_thread(on_log, text)

        def work():
            # Fires when EITHER a track is tagged B OR a Source B path is set: an operator who
            # set Source B must learn it is inert in this mode, not just one who tagged a track.
            if any(t.source2 for t in state.tracks) or (state.source2_path or "").strip():
                log("Uxn mode: ROM owns the bands — per-track A/B tags and Source B "
                    "don't apply (env/rv/euclid/poly/lib/snap/swing/seed do)")
            try:
                cutter.is_wav_export_enabled = bool(state.wav_export)
                cutter.is_verbose_mode_enabled = bool(state.verbose)
                cutter.config_automix(self._uxn_preseed_line(state))
            except Exception as e:
                log(f"Run failed: {e}")
                self.call_from_thread(lambda: self.query_one(RunPanel).set_ready(True))
                return None
            log(f"Uxn: driving {ticks} tick(s) from {os.path.basename(rom)}"
                f"{' (closed-loop)' if state.uxn_feedback else ''}...")

            def on_tick(i, line, phase):
                if phase == "start":
                    mode = describe_line(line).get("m", "?")
                    log(f"[tick {i + 1}/{ticks} · m {mode}] {line}")
                    # Advance to the START of this tick's slice — a progress bar that only moves
                    # when a render FINISHES sits frozen through the slowest part of the loop.
                    self.call_from_thread(on_progress, i / ticks)
                else:
                    self.call_from_thread(on_progress, (i + 1) / ticks)

            try:
                run_uxn_sequence(cutter, ticks, rom_path=rom, closed_loop=state.uxn_feedback,
                                 on_tick=on_tick)
            except Exception as e:
                log(f"Uxn run failed: {e}")
                self.call_from_thread(lambda: self.query_one(RunPanel).set_ready(True))
                return None
            # Renders were exported by run_uxn_sequence's own cutter.automix calls — there is no
            # single "last path" the way _run_single/_run_series track one, so completion is done
            # HERE, not via on_worker_state_changed: that handler only fires _on_finished on a
            # truthy result (load-bearing — _run_single returns None on its own already-handled
            # error path), and _on_finished's Finished(path) would feed self-feed a fake path.
            self.call_from_thread(self._uxn_finished, ticks)
            return None

        self.run_worker(work, thread=True, exit_on_error=False, group="grind")
        return None

    def _uxn_finished(self, ticks):
        """UI-thread completion for the Uxn path: re-enable Run, show the new renders."""
        panel = self.query_one(RunPanel)
        panel._log(f"Uxn: {ticks} tick(s) complete")
        panel.set_ready(True)
        self.query_one(OutputPanel).refresh_list()

    def _run_single(self, state, on_progress, on_log):
        """One-shot grind — the legacy path. Returns the exported mp3 path (or None — completion
        arrives async via the worker message for the real engine; tests inject a sync runner).

        ``build_config`` is called INSIDE ``work()`` (on the worker thread), not before it — it may
        do secondary-source file I/O (``cutter._load_secondary_audio``) that must not block the UI
        thread, and a bad ``source2_path`` must surface as a logged error, not an unhandled
        exception on the caller's thread."""
        def work():
            try:
                cfg = engine.build_config(state.cutter, state)
            except Exception as e:
                self.call_from_thread(on_log, f"Run failed: {e}")
                self.call_from_thread(lambda: self.query_one(RunPanel).set_ready(True))
                return None
            return engine.run(
                cfg, state.output_dir,
                on_progress=lambda f: self.call_from_thread(on_progress, f),
                wav_export=state.wav_export,
                source_path=state.source_path,
            )

        n_filtered = sum(0 if t.bypass else 1 for t in state.tracks)
        on_log(f"Rendering {len(state.tracks)} band(s) ({n_filtered} filtered), "
               f"cut {state.sample_length_ms}ms…")
        self.run_worker(work, thread=True, exit_on_error=False, group="grind")
        return None  # completion arrives async via on_worker_state_changed

    def _run_series(self, state, spec, on_progress, on_log):
        """Series grind (2026-07-19): expand the series spec to a cartesian product of amc token
        lists, render one grind per combination against a CLONE of the live state (so the visible
        params panels are untouched), and return the last exported path. Each combination is logged
        so the operator can correlate file ↔ recipe.

        The live state's panel params form the BASE; the series tokens override the sweepable ones
        per combination. Non-sweepable params (multitrack, snap/fill flags, groove) stay constant
        across the series, exactly as the CLI does.
        """
        import copy as _copy
        from automixer.series import expand_amc_series, apply_amc_to_state, describe_combination, SeriesError

        tokens = ["amc"] + spec.split()
        try:
            combos = expand_amc_series(tokens)
        except SeriesError as e:
            on_log(f"Series error: {e}")
            return None
        n = len(combos)
        on_log(f"Series: {n} combination(s) queued.")

        last_path_holder = {"path": None}

        def log(text):
            self.call_from_thread(on_log, text)

        def work():
            for i, combo in enumerate(combos, 1):
                # Clone the live state so the panels are not mutated as a side-effect of the sweep.
                clone = _copy.copy(state)
                apply_amc_to_state(clone, combo[1:])  # strip leading "amc"
                try:
                    cfg = engine.build_config(clone.cutter, clone)
                except Exception as e:
                    log(f"Run failed: {e}")
                    self.call_from_thread(lambda: self.query_one(RunPanel).set_ready(True))
                    return last_path_holder["path"]
                label = describe_combination(combo[1:]) or f"combo-{i}"
                log(f"[{i}/{n}] {label}  (l={clone.sample_length_ms}ms  s={clone.speed}"
                    f"  ss={clone.sample_speed}  w={clone.window_divider}  m={clone.mode})")
                # Per-combination progress: scale the engine's 0..1 fraction into the i-th slice of
                # n. So the bar advances smoothly across the whole series, not jumping per render.
                base = (i - 1) / n
                span = 1.0 / n
                path = engine.run(
                    cfg, state.output_dir,
                    on_progress=lambda f, b=base, s=span:
                        self.call_from_thread(on_progress, b + s * f),
                    wav_export=state.wav_export,
                    source_path=state.source_path,
                    name_suffix=label,
                )
                last_path_holder["path"] = path
                log(f"[{i}/{n}] done → {os.path.basename(path)}")
            return last_path_holder["path"]

        self.run_worker(work, thread=True, exit_on_error=False, group="grind")
        return None

    def on_worker_state_changed(self, event):
        # Only the grind worker feeds the run panel — the SourcePanel load worker also raises these
        # events (it is a thread worker too) and must NOT be treated as a finished grind.
        if event.worker.group != "grind":
            return
        from textual.worker import WorkerState
        panel = self.query_one(RunPanel)
        if event.state == WorkerState.SUCCESS and event.worker.result:
            panel._on_finished(event.worker.result)
        elif event.state == WorkerState.ERROR:
            # The engine already wrote the recipe + traceback to CRASH_LOG before re-raising.
            # Surface a one-liner here so the operator knows the crash was recorded.
            panel._log(f"Run failed: {event.worker.error}  (recorded in {CRASH_LOG})")
            panel.set_ready(True)


def run_tui(output_dir="output", seed=None, low_memory=False, source=None, uxn_rom=None,
            uxn_ticks=None, uxn_feedback=False):
    """Launch the TUI.

    Every argument here mirrors a CLI flag, and each one is now actually WIRED (2026-07-24) — the
    old signature accepted ``seed`` only to print "accepted but not yet wired", and silently dropped
    the positional source/destination entirely when ``--tui`` was passed. Flags typed at launch are
    a newer statement of intent than the restored session, so they override it.
    """
    state = None
    if any(v is not None for v in (seed, uxn_rom, uxn_ticks)) or uxn_feedback or low_memory:
        prior = SessionState.load()
        state = prior if prior is not None else SessionState()
        state.cutter = None
        if seed is not None:
            state.seed = seed
        if low_memory:
            state.low_memory = True
        if uxn_rom is not None:
            state.uxn_enabled = True
            state.uxn_rom_path = "" if uxn_rom == "__default__" else uxn_rom
        if uxn_ticks is not None:
            state.uxn_ticks = uxn_ticks
        if uxn_feedback:
            state.uxn_feedback = True
    GrainTUI(output_dir=output_dir, low_memory=low_memory, initial_state=state,
             autoload=source).run()
