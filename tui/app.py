import os
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input

from tui.state import SessionState
from tui import engine
from tui.widgets.source_panel import SourcePanel
from tui.widgets.params_panel import ParamsPanel
from tui.widgets.tracks_panel import TracksPanel
from tui.widgets.run_panel import RunPanel
from tui.widgets.output_panel import OutputPanel


def _real_loader(value):
    from cutter.sample_cut_tool import SampleCutter
    out = os.path.abspath("output")
    os.makedirs(out, exist_ok=True)
    if value.startswith("http://") or value.startswith("https://"):
        import youtube.downloader as downloader
        value = downloader.download_video(value, out)
    return SampleCutter(os.path.abspath(value), out)


def _real_player(path):
    from pydub import AudioSegment
    import pydub.playback
    pydub.playback.play(AudioSegment.from_file(path))


class GrainTUI(App):
    CSS = """
    #top { height: 1fr; }
    #left { width: 1fr; }
    #right { width: 1fr; }
    ParamsPanel Grid { grid-size: 2; grid-rows: auto; height: auto; }
    TracksPanel { height: 1fr; }
    RichLog { height: 1fr; }
    """
    BINDINGS = [("r", "run", "Run"), ("q", "quit", "Quit")]

    def __init__(self, output_dir="output", loader=None, player=None):
        super().__init__()
        self.state = SessionState(output_dir=output_dir)
        self._loader = loader or _real_loader
        self._player = player or _real_player

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            with Vertical(id="left"):
                yield SourcePanel(self._loader)
                yield ParamsPanel(self.state)
                yield TracksPanel(self.state.tracks)
            with Vertical(id="right"):
                yield RunPanel(self.state, self._threaded_runner)
                yield OutputPanel(self.state.output_dir, self._player)
        yield Footer()

    # --- wiring ---
    def on_source_panel_loaded(self, msg):
        self.state.cutter = msg.cutter
        step = int(getattr(msg.cutter, "step", 0) or 0)
        if step > 0:
            self.state.sample_length_ms = step
            try:
                self.query_one("#sample_length", Input).value = str(step)
            except Exception:
                pass

    def on_tracks_panel_changed(self, msg):
        self.state.tracks = msg.tracks

    def on_run_panel_finished(self, msg):
        self.query_one(OutputPanel).refresh_list()

    def action_run(self):
        self.query_one(ParamsPanel).apply_to_state()
        self.query_one(RunPanel).start()

    # --- real threaded runner injected into RunPanel ---
    def _threaded_runner(self, state, on_progress, on_log):
        self.query_one(ParamsPanel).apply_to_state()
        cfg = engine.build_config(state.cutter, state)

        def work():
            return engine.run(
                cfg, state.output_dir,
                on_progress=lambda f: self.call_from_thread(on_progress, f),
            )

        on_log(f"Rendering {len(state.tracks)} track(s), cut {state.sample_length_ms}ms...")
        self.run_worker(work, thread=True, exit_on_error=False)
        return None  # completion arrives async via on_worker_state_changed

    def on_worker_state_changed(self, event):
        from textual.worker import WorkerState
        panel = self.query_one(RunPanel)
        if event.state == WorkerState.SUCCESS and event.worker.result:
            panel._on_finished(event.worker.result)
        elif event.state == WorkerState.ERROR:
            panel._log(f"Run failed: {event.worker.error}")
            try:
                self.query_one("#run_btn", Button).disabled = False
            except Exception:
                pass


def run_tui(output_dir="output"):
    GrainTUI(output_dir=output_dir).run()
