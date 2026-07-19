import os
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Input

from tui.state import SessionState
from tui import engine
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


class GrainTUI(App):
    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+r", "run", "Run grind"),
        ("i", "info", "Info"),
        ("f1", "help", "Help"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, output_dir="output", loader=None, player=None, low_memory=False):
        super().__init__()
        self.state = SessionState(output_dir=output_dir)
        self._loader = loader or _real_loader
        self._player = player or _real_player
        self.low_memory = low_memory

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

    # --- wiring ---
    def on_source_panel_loading(self, msg):
        self.state.cutter = None
        self.query_one(RunPanel).set_ready(False, "loading source…")

    def on_source_panel_failed(self, msg):
        self.state.cutter = None
        self.query_one(RunPanel).set_ready(False, "load a source first")

    def on_source_panel_loaded(self, msg):
        self.state.cutter = msg.cutter
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

    def on_tracks_panel_changed(self, msg):
        self.state.tracks = msg.tracks

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
        self.query_one(RunPanel).start()

    def action_help(self):
        self.notify(
            "Enter a file/URL in Source → Enter (watch the download progress).\n"
            "When it says ✓ Loaded, press Ctrl+R (or the Run button) to grind.\n"
            "Tracks: a add · d remove · edit low/high + Set for multitrack.\n"
            "Run opts: WAV export · Verbose · Self-feed (reload the mix as source).\n"
            "i: dump live source + config.   Outputs: p play · g refresh.   Quit: q",
            title="How to grind", timeout=12)

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
            panel._log(f"Run failed: {event.worker.error}")
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
