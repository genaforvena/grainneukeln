import os
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Input, Select, DataTable

from tui.state import SessionState, SESSION_PATH, CRASH_LOG
from tui import engine
from tui.player import make_player
from tui.theme import grain_theme
from tui.widgets.banner import Banner
from tui.widgets.source_panel import SourcePanel
from tui.widgets.params_panel import ParamsPanel
from tui.widgets.mode_panel import ModePanel
from tui.widgets.tracks_panel import TracksPanel
from tui.widgets.run_panel import RunPanel
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
    # (a/d in tracks, p/g in outputs) are panel-LOCAL — they fire only when that panel has focus, so
    # typing 'a' in the source path inserts 'a' rather than adding a track. Use Ctrl+4 to focus the
    # tracks panel, then 'a' adds a track. Help (?) lists the full keymap.
    BINDINGS = [
        ("ctrl+r", "run", "Run grind"),
        ("ctrl+l", "focus_source", "Focus source"),
        Binding("ctrl+1", "focus_panel('1')", "Source", show=False),
        Binding("ctrl+2", "focus_panel('2')", "Params", show=False),
        Binding("ctrl+3", "focus_panel('3')", "Mode", show=False),
        Binding("ctrl+4", "focus_panel('4')", "Tracks", show=False),
        Binding("ctrl+5", "focus_panel('5')", "Run", show=False),
        Binding("ctrl+6", "focus_panel('6')", "Outputs", show=False),
        ("i", "info", "Info"),
        ("f1,question", "help", "Help"),
        ("ctrl+t", "open_crash_log", "Crash log"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, output_dir="output", loader=None, player=None, low_memory=False,
                 session_path=SESSION_PATH):
        super().__init__()
        # Restore the last session BEFORE the panels compose — they read state to seed themselves.
        # None on first run (no prior session); a previous SessionState on restart-after-crash.
        prior = SessionState.load(session_path)
        if prior is not None:
            # cutter is not serialized — re-load from source_path lazily (the user re-presses Enter
            # or the load is auto-triggered on mount). Output_dir from prior if set, else caller's.
            self.state = prior
            self.state.cutter = None
            self.state.output_dir = output_dir or prior.output_dir
        else:
            self.state = SessionState(output_dir=output_dir)
        self._loader = loader or _real_loader
        # Player: a Player instance (preferred — supports start/stop/pause/seek) or a legacy
        # ``player(path)`` callable (existing tests inject these). Default: pick the best for the node.
        self._player = player if player is not None else make_player()
        self.low_memory = low_memory
        self._session_path = session_path

    def compose(self) -> ComposeResult:
        yield Banner()
        with Horizontal(id="top"):
            with Vertical(id="left"):
                yield SourcePanel(self._loader)
                yield ParamsPanel(self.state)
                yield ModePanel(self.state)
                yield TracksPanel(self.state.tracks)
            with Vertical(id="right"):
                yield RunPanel(self.state, self._threaded_runner)
                yield OutputPanel(self.state.output_dir, self._player)
        yield Footer()

    def on_mount(self):
        self.register_theme(grain_theme)
        self.theme = "grain"
        self.title = "grainneukeln"
        self.sub_title = "granular grinder"
        self.query_one(ParamsPanel).border_title = "◈ 2 · grind params"
        self.query_one(ParamsPanel).border_subtitle = "speed · window · length"
        self.query_one(ModePanel).border_title = "◈ 3 · mixer & effects"
        self.query_one(ModePanel).border_subtitle = "mode · euclid · poly · lib · snap · swing"
        self.query_one(OutputPanel).border_title = "♫ outputs"
        # If the restored session had a source, drop it into the source input so the operator can
        # press Enter to reload (or it auto-loads). Don't silently re-load — a crashed session may
        # have crashed BECAUSE of that source's grind, and the operator chooses whether to retry.
        if self.state.source_path:
            try:
                self.query_one("#source_input", Input).value = self.state.source_path
            except Exception:
                pass

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

    # --- wiring ---
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
        self._save_session()

    def on_tracks_panel_changed(self, msg):
        self.state.tracks = msg.tracks
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
        tracks = " ".join(f"{t.low}-{t.high}" for t in s.tracks) or "(none)"
        streams = s.streams_spec or "(mixer default)"
        panel._log(
            f"Source: {os.path.basename(path)} · {n_beats} beats · beat={beat}ms\n"
            f"  mode={s.mode}  l={s.sample_length_ms}ms  s={s.speed}  ss={s.sample_speed}"
            f"  w={s.window_divider}\n"
            f"  bands: {tracks}\n"
            f"  euclid E({s.euclid_k},{s.euclid_n}) · swing={s.swing} · snap={s.snap}"
            f" · fill={'on' if s.fill else 'off'}({s.fill_gain_db}dB)\n"
            f"  lib: {s.lib_policy}/{s.lib_clusters} · poly: {streams}\n"
            f"  out: wav={'on' if s.wav_export else 'off'}"
            f" verbose={'on' if s.verbose else 'off'}"
            f" self-feed={'on' if s.self_feed else 'off'}"
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
        self.query_one(RunPanel).start()

    def action_help(self):
        self.notify(
            "KEYBOARD (no mouse needed):\n"
            "  Source: type path/URL → Enter to load.\n"
            "  Jump panels: Ctrl+1 source · Ctrl+2 params · Ctrl+3 mode · Ctrl+4 tracks\n"
            "               · Ctrl+5 run · Ctrl+6 outputs.  (Tab also cycles.)\n"
            "  Tracks (Ctrl+4 first): a add · d remove · type low/high + Enter.\n"
            "  Outputs (Ctrl+6 first): space play/pause · s stop · . ff 10s · , back 10s · g refresh.\n"
            "  Run: Ctrl+R · Info: i · Crash log: Ctrl+T · Help: ? · Quit: q.\n"
            "Crash-tolerant: state is saved before every grind — restart after a crash restores it.",
            title="How to grind", timeout=14)

    def action_focus_source(self):
        """Ctrl+L: jump straight to the source input and select-all so a new path overwrites."""
        try:
            inp = self.query_one("#source_input", Input)
            self.set_focus(inp)
            inp.focus()
        except Exception:
            pass

    def action_focus_panel(self, which):
        """Ctrl+1..6: jump to each panel. Always fires (Ctrl-prefixed — does not conflict with
        typing digits into Inputs).

        Panels extend Static and have ``can_focus=False`` — calling ``.focus()`` on the panel itself
        does nothing. We walk descendants and focus the FIRST focusable child (Input/Select/DataTable/
        Button/Checkbox/ListView), so Ctrl+2 lands on the speed Input inside ParamsPanel, and Ctrl+4
        lands on the tracks DataTable (so 'a'/'d' panel-local bindings work right after the jump)."""
        cmap = {
            "1": SourcePanel, "2": ParamsPanel, "3": ModePanel,
            "4": TracksPanel, "5": RunPanel, "6": OutputPanel,
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
        the TUI. The log is append-only — show the last entry (the most recent crash)."""
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
        last = ("[" + blocks[-1]) if blocks else text[-1500:]
        self.notify(last.strip()[:1500], title="Last crash", timeout=14)

    # --- real threaded runner injected into RunPanel ---
    def _threaded_runner(self, state, on_progress, on_log):
        self.query_one(ParamsPanel).apply_to_state()
        self.query_one(ModePanel).apply_to_state()
        cfg = engine.build_config(state.cutter, state)

        def work():
            return engine.run(
                cfg, state.output_dir,
                on_progress=lambda f: self.call_from_thread(on_progress, f),
                wav_export=state.wav_export,
                source_path=state.source_path,
            )

        on_log(f"Rendering {len(state.tracks)} track(s), cut {state.sample_length_ms}ms…")
        self.run_worker(work, thread=True, exit_on_error=False, group="grind")
        return None  # completion arrives async via on_worker_state_changed

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


def run_tui(output_dir="output", seed=None, low_memory=False):
    """Launch the TUI. ``seed`` (from ``main.py --seed``) is accepted for symmetry with the CLI but
    not yet wired into the TUI's session state — the TUI's own params panel is the primary seed
    surface there. The arg is accepted so ``main.py --seed N --tui`` does not raise.
    ``low_memory`` enables aggressive GC for memory-constrained nodes."""
    if seed is not None:
        print(f"[tui] note: --seed {seed} accepted but not yet wired into the TUI session state; "
              f"the CLI path (no --tui) honours it end-to-end.")
    GrainTUI(output_dir=output_dir, low_memory=low_memory).run()
