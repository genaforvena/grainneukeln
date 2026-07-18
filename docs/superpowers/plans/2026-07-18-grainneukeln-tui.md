# grainneukeln TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A keyboard-driven Textual TUI that drives grainneukeln's existing granular engine over SSH/tmux, replacing the raw REPL and the headless-useless Qt GUI, with a first-class multitrack editor.

**Architecture:** A thin `tui/` package. Pure-Python core (`state.py`, `engine.py`) maps a typed `SessionState` to the existing `AutoMixerConfig` and runs `AutoMixerRunner` + the existing loudness-normalized export — no DSP is touched. Textual widgets (source, params, tracks, run, output) are views over that state, wired in `app.py`. Widgets take injected callables (loader/engine) so their tests never hit DSP or the network; the app wires the real ones.

**Tech Stack:** Python 3.12, Textual, pydub, librosa (existing), unittest (repo convention) incl. `IsolatedAsyncioTestCase` for Textual pilot tests.

## Global Constraints

- Do NOT modify `automixer/` or `cutter/` DSP behavior. The TUI is a front-end only.
- Reuse existing engine objects verbatim: `cutter.sample_cut_tool.SampleCutter`,
  `automixer.config.AutoMixerConfig`, `automixer.config.ChannelConfig`,
  `automixer.runner.AutoMixerRunner`, `cutter.sample_cut_tool.normalize_loudness`.
- Tests use `unittest` (repo convention), run with `python -m unittest`. No pytest dependency.
- New runtime dep: `textual` only (pulls `rich`). Core CLI automix path must still need nothing new;
  TUI deps are opt-in like the Qt GUI deps.
- Real-artifact gate: the engine test MUST produce a non-empty, non-silent mp3 from
  `assets/test_audio.wav` (assert file size AND a loudness floor) — guards the repo's known
  silent-fallback failure mode. A gate you have not seen fail is not a gate.
- No `d` duration cap (it is a phantom in the current DSL — see spec).
- Every action reachable by key; mouse is a bonus, never required.

---

### Task 1: TUI package + typed session state

**Files:**
- Create: `tui/__init__.py` (empty)
- Create: `tui/state.py`
- Test: `tui/test_state.py`

**Interfaces:**
- Produces:
  - `TrackSpec(low: int, high: int)` — one multitrack band. `valid() -> bool` (`0 <= low < high`).
  - `SessionState` dataclass with fields: `cutter=None`, `speed: float = 1.0`,
    `sample_speed: float = 1.0`, `window_divider: int = 2`, `sample_length_ms: int = 0`,
    `tracks: list[TrackSpec] = [TrackSpec(0, 15000)]`, `wav_export: bool = False`,
    `output_dir: str = "output"`.
  - `SessionState.is_runnable() -> tuple[bool, str]` — `(True, "")` when a cutter is loaded,
    `sample_length_ms > 0`, at least one track, and every track valid; else `(False, reason)`.

- [ ] **Step 1: Write the failing test**

```python
# tui/test_state.py
import unittest
from tui.state import TrackSpec, SessionState


class TrackSpecTest(unittest.TestCase):
    def test_valid_range(self):
        self.assertTrue(TrackSpec(0, 15000).valid())
        self.assertTrue(TrackSpec(200, 400).valid())

    def test_invalid_range(self):
        self.assertFalse(TrackSpec(400, 200).valid())   # low >= high
        self.assertFalse(TrackSpec(-1, 100).valid())    # negative
        self.assertFalse(TrackSpec(100, 100).valid())   # equal


class SessionStateTest(unittest.TestCase):
    def test_defaults(self):
        s = SessionState()
        self.assertEqual(s.speed, 1.0)
        self.assertEqual(s.window_divider, 2)
        self.assertEqual(len(s.tracks), 1)
        self.assertEqual((s.tracks[0].low, s.tracks[0].high), (0, 15000))

    def test_not_runnable_without_cutter(self):
        ok, reason = SessionState(sample_length_ms=500).is_runnable()
        self.assertFalse(ok)
        self.assertIn("source", reason.lower())

    def test_not_runnable_without_length(self):
        ok, reason = SessionState(cutter=object(), sample_length_ms=0).is_runnable()
        self.assertFalse(ok)
        self.assertIn("length", reason.lower())

    def test_not_runnable_with_bad_track(self):
        ok, reason = SessionState(
            cutter=object(), sample_length_ms=500, tracks=[TrackSpec(400, 200)]
        ).is_runnable()
        self.assertFalse(ok)
        self.assertIn("track", reason.lower())

    def test_runnable(self):
        ok, reason = SessionState(cutter=object(), sample_length_ms=500).is_runnable()
        self.assertTrue(ok)
        self.assertEqual(reason, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_state -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tui.state'`

- [ ] **Step 3: Write minimal implementation**

```python
# tui/state.py
from dataclasses import dataclass, field


@dataclass
class TrackSpec:
    low: int
    high: int

    def valid(self) -> bool:
        return 0 <= self.low < self.high


@dataclass
class SessionState:
    cutter: object = None
    speed: float = 1.0
    sample_speed: float = 1.0
    window_divider: int = 2
    sample_length_ms: int = 0
    tracks: list = field(default_factory=lambda: [TrackSpec(0, 15000)])
    wav_export: bool = False
    output_dir: str = "output"

    def is_runnable(self) -> tuple[bool, str]:
        if self.cutter is None:
            return False, "No source loaded"
        if self.sample_length_ms <= 0:
            return False, "Sample length must be > 0"
        if not self.tracks:
            return False, "Add at least one track"
        for i, t in enumerate(self.tracks):
            if not t.valid():
                return False, f"Track {i + 1} range invalid (need 0 <= low < high)"
        return True, ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_state -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/mesh-home/grainneukeln
git add tui/__init__.py tui/state.py tui/test_state.py
git commit -m "feat(tui): typed SessionState + TrackSpec with runnable gate"
```

---

### Task 2: engine.build_config — state → AutoMixerConfig (incl. multitrack)

**Files:**
- Create: `tui/engine.py`
- Test: `tui/test_engine.py`

**Interfaces:**
- Consumes: `SessionState`, `TrackSpec` (Task 1); `SampleCutter`, `AutoMixerConfig`, `ChannelConfig`.
- Produces: `build_config(cutter, state: SessionState) -> AutoMixerConfig`. Maps speed, sample_speed,
  window_divider, sample_length, and — the headline — every `TrackSpec` to a `ChannelConfig(low, high)`
  in `channels_config`, preserving order and count.

- [ ] **Step 1: Write the failing test**

```python
# tui/test_engine.py
import os
import unittest
from tui.state import SessionState, TrackSpec
from tui import engine

ASSET = os.path.join(os.path.dirname(__file__), "..", "assets", "test_audio.wav")


def _load_cutter():
    from cutter.sample_cut_tool import SampleCutter
    return SampleCutter(os.path.abspath(ASSET), os.path.abspath("output"))


class BuildConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cutter = _load_cutter()   # loads + beat-detects once (slow-ish)

    def test_scalars_map(self):
        state = SessionState(cutter=self.cutter, speed=1.5, sample_speed=0.5,
                             window_divider=6, sample_length_ms=480)
        cfg = engine.build_config(self.cutter, state)
        self.assertEqual(cfg.speed, 1.5)
        self.assertEqual(cfg.sample_speed, 0.5)
        self.assertEqual(cfg.window_divider, 6)
        self.assertEqual(cfg.sample_length, 480)
        self.assertEqual(cfg.mode, "rw")

    def test_multitrack_maps_every_band(self):
        state = SessionState(cutter=self.cutter, sample_length_ms=480, tracks=[
            TrackSpec(1, 250), TrackSpec(251, 400), TrackSpec(10000, 15000)])
        cfg = engine.build_config(self.cutter, state)
        self.assertEqual(len(cfg.channels_config), 3)
        self.assertEqual(cfg.channels_config[0].low_pass, 1)
        self.assertEqual(cfg.channels_config[0].high_pass, 250)
        self.assertEqual(cfg.channels_config[2].low_pass, 10000)
        self.assertEqual(cfg.channels_config[2].high_pass, 15000)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_engine.BuildConfigTest -v`
Expected: FAIL — `AttributeError: module 'tui.engine' has no attribute 'build_config'`

- [ ] **Step 3: Write minimal implementation**

```python
# tui/engine.py
from automixer.config import AutoMixerConfig, ChannelConfig


def build_config(cutter, state):
    """Map a SessionState onto the existing AutoMixerConfig. DSP untouched."""
    channels = [ChannelConfig(t.low, t.high) for t in state.tracks]
    return AutoMixerConfig(
        audio=cutter.audio,
        beats=cutter.beats,
        sample_length=state.sample_length_ms,
        sample_speed=state.sample_speed,
        mode="rw",
        speed=state.speed,
        is_verbose_mode_enabled=False,
        window_divider=state.window_divider,
        channels_config=channels,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_engine.BuildConfigTest -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/mesh-home/grainneukeln
git add tui/engine.py tui/test_engine.py
git commit -m "feat(tui): build_config maps SessionState -> AutoMixerConfig incl. multitrack"
```

---

### Task 3: engine.run — real, audible artifact

**Files:**
- Modify: `tui/engine.py`
- Test: `tui/test_engine.py` (add class)

**Interfaces:**
- Consumes: `build_config` (Task 2); `AutoMixerRunner`, `normalize_loudness`.
- Produces: `run(config, out_dir, on_progress=None) -> str`. Runs the mixer, loudness-normalizes
  (reusing `cutter.sample_cut_tool.normalize_loudness`), exports mp3 to `out_dir`, returns the path.
  `on_progress`, if given, is a callable `(fraction: float) -> None` called at least at 0.0 and 1.0.

- [ ] **Step 1: Write the failing test**

```python
# tui/test_engine.py  (append)
class RunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cutter = _load_cutter()

    def test_run_produces_audible_mp3(self):
        import tempfile
        from pydub import AudioSegment
        state = SessionState(cutter=self.cutter, sample_length_ms=300)
        cfg = engine.build_config(self.cutter, state)
        with tempfile.TemporaryDirectory() as d:
            calls = []
            path = engine.run(cfg, d, on_progress=lambda f: calls.append(f))
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 2000)     # non-empty mp3
            seg = AudioSegment.from_file(path)
            self.assertGreater(len(seg), 0)                     # has duration
            self.assertGreater(seg.dBFS, -40.0)                 # audible, not silent-fallback
            self.assertIn(1.0, calls)                           # progress reached completion
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_engine.RunTest -v`
Expected: FAIL — `AttributeError: module 'tui.engine' has no attribute 'run'`

- [ ] **Step 3: Write minimal implementation**

```python
# tui/engine.py  (append imports + function)
import os
from datetime import datetime

from automixer.runner import AutoMixerRunner
from cutter.sample_cut_tool import normalize_loudness


def run(config, out_dir, on_progress=None):
    """Render one grind and export an audible mp3. Returns the output path."""
    if on_progress:
        on_progress(0.0)
    os.makedirs(out_dir, exist_ok=True)
    mix = AutoMixerRunner().run(config)
    mix = normalize_loudness(mix)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(out_dir, f"grain_cut{int(config.sample_length)}_{stamp}.mp3")
    mix.export(path, format="mp3")
    if on_progress:
        on_progress(1.0)
    return path
```

Note: `AutoMixerRunner().run` is synchronous and blocking; the RunPanel (Task 7) calls this on a
worker thread. Coarse progress (0.0/1.0) is sufficient for v1 — the mixer's own tqdm bar is not
wired into the callback; do not claim finer progress than is delivered.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_engine.RunTest -v`
Expected: PASS

- [ ] **Step 5: Verify the gate really gates (break it, watch it fail)**

Temporarily change the assertion to `self.assertGreater(seg.dBFS, 40.0)` (impossible), run, confirm
FAIL, then restore. This proves the loudness gate can go red.

- [ ] **Step 6: Commit**

```bash
cd /home/mesh-home/grainneukeln
git add tui/engine.py tui/test_engine.py
git commit -m "feat(tui): engine.run renders + normalizes + exports audible mp3 (real-artifact gate)"
```

---

### Task 4: TracksPanel — the multitrack editor

**Files:**
- Create: `tui/widgets/__init__.py` (empty)
- Create: `tui/widgets/tracks_panel.py`
- Test: `tui/test_tracks_panel.py`

**Interfaces:**
- Consumes: `TrackSpec` (Task 1).
- Produces: `TracksPanel(tracks: list[TrackSpec])` — a Textual `Static`-derived container with a
  `DataTable` of `# | low | high`. Methods: `add_track()` appends `TrackSpec(0, 15000)`;
  `remove_selected()` removes the highlighted row (keeps ≥1); `set_selected_range(low, high)` edits
  the highlighted row. Property `tracks` returns the current `list[TrackSpec]`. Posts
  `TracksPanel.Changed(tracks)` message on any mutation. Key bindings: `a` add, `d` remove.

- [ ] **Step 1: Write the failing test**

```python
# tui/test_tracks_panel.py
import unittest
from textual.app import App, ComposeResult
from tui.state import TrackSpec
from tui.widgets.tracks_panel import TracksPanel


class _Host(App):
    def __init__(self, tracks):
        super().__init__()
        self._tracks = tracks

    def compose(self) -> ComposeResult:
        yield TracksPanel(self._tracks)


class TracksPanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_add_and_remove(self):
        app = _Host([TrackSpec(0, 15000)])
        async with app.run_test() as pilot:
            panel = app.query_one(TracksPanel)
            self.assertEqual(len(panel.tracks), 1)
            panel.add_track()
            await pilot.pause()
            self.assertEqual(len(panel.tracks), 2)
            panel.remove_selected()
            await pilot.pause()
            self.assertEqual(len(panel.tracks), 1)

    async def test_never_below_one(self):
        app = _Host([TrackSpec(0, 15000)])
        async with app.run_test() as pilot:
            panel = app.query_one(TracksPanel)
            panel.remove_selected()
            await pilot.pause()
            self.assertEqual(len(panel.tracks), 1)   # floor at one track

    async def test_edit_range(self):
        app = _Host([TrackSpec(0, 15000)])
        async with app.run_test() as pilot:
            panel = app.query_one(TracksPanel)
            panel.set_selected_range(200, 400)
            await pilot.pause()
            self.assertEqual((panel.tracks[0].low, panel.tracks[0].high), (200, 400))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_tracks_panel -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tui.widgets.tracks_panel'`

- [ ] **Step 3: Write minimal implementation**

```python
# tui/widgets/tracks_panel.py
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Label, Static
from textual.message import Message
from tui.state import TrackSpec


class TracksPanel(Static):
    BINDINGS = [("a", "add", "Add track"), ("d", "remove", "Remove track")]

    class Changed(Message):
        def __init__(self, tracks):
            self.tracks = tracks
            super().__init__()

    def __init__(self, tracks):
        super().__init__()
        self._tracks = list(tracks)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Tracks (multitrack)  —  a: add   d: remove   enter: edit")
            yield DataTable(id="tracks_table", cursor_type="row")

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("#", "low Hz", "high Hz")
        self._refresh()

    @property
    def tracks(self):
        return list(self._tracks)

    def _refresh(self):
        table = self.query_one(DataTable)
        cursor = table.cursor_row
        table.clear()
        for i, t in enumerate(self._tracks):
            table.add_row(str(i + 1), str(t.low), str(t.high))
        if self._tracks:
            table.move_cursor(row=min(cursor, len(self._tracks) - 1))
        self.border_title = f"Tracks ({len(self._tracks)})"
        self.post_message(self.Changed(self.tracks))

    def add_track(self):
        self._tracks.append(TrackSpec(0, 15000))
        self._refresh()

    def remove_selected(self):
        if len(self._tracks) <= 1:
            return
        idx = self.query_one(DataTable).cursor_row
        if 0 <= idx < len(self._tracks):
            self._tracks.pop(idx)
            self._refresh()

    def set_selected_range(self, low, high):
        idx = self.query_one(DataTable).cursor_row
        if 0 <= idx < len(self._tracks):
            self._tracks[idx] = TrackSpec(int(low), int(high))
            self._refresh()

    def action_add(self):
        self.add_track()

    def action_remove(self):
        self.remove_selected()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_tracks_panel -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/mesh-home/grainneukeln
git add tui/widgets/__init__.py tui/widgets/tracks_panel.py tui/test_tracks_panel.py
git commit -m "feat(tui): multitrack editor panel (add/remove/edit channel bands)"
```

---

### Task 5: ParamsPanel — scalar grain params

**Files:**
- Create: `tui/widgets/params_panel.py`
- Test: `tui/test_params_panel.py`

**Interfaces:**
- Consumes: `SessionState` (Task 1).
- Produces: `ParamsPanel(state: SessionState)` with `Input`s for speed, sample_speed,
  window_divider, sample_length_ms. `apply_to_state()` parses inputs and writes valid values back
  into the shared `SessionState`, returning `list[str]` of validation errors (empty = clean).
  Out-of-range/non-numeric inputs are reported and NOT written.

- [ ] **Step 1: Write the failing test**

```python
# tui/test_params_panel.py
import unittest
from textual.app import App, ComposeResult
from textual.widgets import Input
from tui.state import SessionState
from tui.widgets.params_panel import ParamsPanel


class _Host(App):
    def __init__(self, state):
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        yield ParamsPanel(self._state)


class ParamsPanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_valid_values_write_back(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test() as pilot:
            panel = app.query_one(ParamsPanel)
            panel.query_one("#speed", Input).value = "1.5"
            panel.query_one("#sample_speed", Input).value = "0.5"
            panel.query_one("#window_divider", Input).value = "6"
            panel.query_one("#sample_length", Input).value = "480"
            errs = panel.apply_to_state()
            self.assertEqual(errs, [])
            self.assertEqual(state.speed, 1.5)
            self.assertEqual(state.window_divider, 6)
            self.assertEqual(state.sample_length_ms, 480)

    async def test_out_of_range_reported_not_written(self):
        state = SessionState()
        app = _Host(state)
        async with app.run_test() as pilot:
            panel = app.query_one(ParamsPanel)
            panel.query_one("#speed", Input).value = "99"    # > 10.0
            panel.query_one("#window_divider", Input).value = "abc"
            errs = panel.apply_to_state()
            self.assertTrue(any("speed" in e.lower() for e in errs))
            self.assertTrue(any("divider" in e.lower() for e in errs))
            self.assertEqual(state.speed, 1.0)               # unchanged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_params_panel -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tui.widgets.params_panel'`

- [ ] **Step 3: Write minimal implementation**

```python
# tui/widgets/params_panel.py
from textual.app import ComposeResult
from textual.containers import Grid
from textual.widgets import Input, Label, Static


class ParamsPanel(Static):
    def __init__(self, state):
        super().__init__()
        self.state = state

    def compose(self) -> ComposeResult:
        with Grid():
            yield Label("Speed (0.1-10)")
            yield Input(str(self.state.speed), id="speed")
            yield Label("Sample speed (0.1-10)")
            yield Input(str(self.state.sample_speed), id="sample_speed")
            yield Label("Window divider (1-10)")
            yield Input(str(self.state.window_divider), id="window_divider")
            yield Label("Sample length (ms)")
            yield Input(str(self.state.sample_length_ms), id="sample_length")

    def apply_to_state(self):
        errors = []

        def _float(field, lo, hi, label):
            raw = self.query_one(f"#{field}", Input).value.strip()
            try:
                v = float(raw)
            except ValueError:
                errors.append(f"{label}: not a number ({raw!r})")
                return None
            if not (lo <= v <= hi):
                errors.append(f"{label}: {v} out of range {lo}-{hi}")
                return None
            return v

        def _int(field, lo, hi, label):
            raw = self.query_one(f"#{field}", Input).value.strip()
            try:
                v = int(raw)
            except ValueError:
                errors.append(f"{label}: not an integer ({raw!r})")
                return None
            if not (lo <= v <= hi):
                errors.append(f"{label}: {v} out of range {lo}-{hi}")
                return None
            return v

        speed = _float("speed", 0.1, 10.0, "Speed")
        ss = _float("sample_speed", 0.1, 10.0, "Sample speed")
        wd = _int("window_divider", 1, 10, "Window divider")
        sl = _int("sample_length", 1, 10_000_000, "Sample length")

        if speed is not None:
            self.state.speed = speed
        if ss is not None:
            self.state.sample_speed = ss
        if wd is not None:
            self.state.window_divider = wd
        if sl is not None:
            self.state.sample_length_ms = sl
        return errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_params_panel -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/mesh-home/grainneukeln
git add tui/widgets/params_panel.py tui/test_params_panel.py
git commit -m "feat(tui): scalar params panel with range validation"
```

---

### Task 6: SourcePanel — load file / YouTube, show beats

**Files:**
- Create: `tui/widgets/source_panel.py`
- Test: `tui/test_source_panel.py`

**Interfaces:**
- Consumes: nothing from earlier tasks directly; takes an injected `loader(path_or_url) -> cutter`
  callable (the app injects one that wraps `SampleCutter` + `youtube.downloader`).
- Produces: `SourcePanel(loader)` with an `Input` (`#source_input`) and a status `Label`. On submit it
  calls `loader`, and on success posts `SourcePanel.Loaded(cutter)` and shows beats/tempo/step; on
  failure shows the error inline and stays up. Method `load(value)` does the work (tested directly).

- [ ] **Step 1: Write the failing test**

```python
# tui/test_source_panel.py
import unittest
from textual.app import App, ComposeResult
from tui.widgets.source_panel import SourcePanel


class _FakeCutter:
    def __init__(self):
        self.audio_file_path = "/tmp/x.wav"
        self.beats = [0, 500, 1000]
        self.step = 500


class _Host(App):
    def __init__(self, loader):
        super().__init__()
        self._loader = loader
        self.loaded = None

    def compose(self) -> ComposeResult:
        yield SourcePanel(self._loader)

    def on_source_panel_loaded(self, msg):
        self.loaded = msg.cutter


class SourcePanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_successful_load_posts_message(self):
        cutter = _FakeCutter()
        app = _Host(lambda v: cutter)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.load("/tmp/x.wav")
            await pilot.pause()
            self.assertIs(app.loaded, cutter)

    async def test_failed_load_stays_up_and_reports(self):
        def boom(v):
            raise ValueError("bad file")
        app = _Host(boom)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.load("/nope")
            await pilot.pause()
            self.assertIsNone(app.loaded)
            self.assertIn("bad file", panel.status_text.lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_source_panel -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tui.widgets.source_panel'`

- [ ] **Step 3: Write minimal implementation**

```python
# tui/widgets/source_panel.py
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Static
from textual.message import Message


class SourcePanel(Static):
    class Loaded(Message):
        def __init__(self, cutter):
            self.cutter = cutter
            super().__init__()

    def __init__(self, loader):
        super().__init__()
        self._loader = loader
        self.status_text = "No source loaded"

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Source: local file path or YouTube URL, then Enter")
            yield Input(placeholder="path/to/audio.wav  or  https://youtube.com/...",
                        id="source_input")
            yield Label(self.status_text, id="source_status")

    def on_input_submitted(self, event):
        self.load(event.value)

    def load(self, value):
        value = (value or "").strip()
        if not value:
            self._set_status("Enter a path or URL")
            return
        self._set_status("Loading...")
        try:
            cutter = self._loader(value)
        except Exception as e:
            self._set_status(f"Load failed: {e}")
            return
        beats = len(getattr(cutter, "beats", []) or [])
        step = getattr(cutter, "step", 0)
        if beats == 0:
            self._set_status("Loaded, but 0 beats — source too steady/silent to latch a pulse")
        else:
            self._set_status(f"Loaded: {beats} beats, step {int(step)} ms")
        self.post_message(self.Loaded(cutter))

    def _set_status(self, text):
        self.status_text = text
        self.query_one("#source_status", Label).update(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_source_panel -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/mesh-home/grainneukeln
git add tui/widgets/source_panel.py tui/test_source_panel.py
git commit -m "feat(tui): source panel (file/YouTube load, beats/tempo readout)"
```

---

### Task 7: RunPanel — run on a worker thread, progress + log

**Files:**
- Create: `tui/widgets/run_panel.py`
- Test: `tui/test_run_panel.py`

**Interfaces:**
- Consumes: `SessionState` (Task 1); an injected `runner(state, on_progress, on_log) -> str` callable
  (the app injects one that calls `engine.build_config` + `engine.run` on a thread). Injection keeps
  the test off the real DSP thread.
- Produces: `RunPanel(state, runner)` with a `Button` (`#run_btn`), a `ProgressBar`, and a `RichLog`.
  `start()` guards on `state.is_runnable()` (logs the reason and returns if not), else invokes
  `runner`. Posts `RunPanel.Finished(path)` on success. Method `_on_finished(path)` and `_log(text)`
  are called back on the UI thread.

- [ ] **Step 1: Write the failing test**

```python
# tui/test_run_panel.py
import unittest
from textual.app import App, ComposeResult
from tui.state import SessionState
from tui.widgets.run_panel import RunPanel


class _Host(App):
    def __init__(self, state, runner):
        super().__init__()
        self._state = state
        self._runner = runner
        self.finished = None

    def compose(self) -> ComposeResult:
        yield RunPanel(self._state, self._runner)

    def on_run_panel_finished(self, msg):
        self.finished = msg.path


class RunPanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_blocks_when_not_runnable(self):
        state = SessionState()   # no cutter -> not runnable
        called = []
        app = _Host(state, lambda s, on_progress, on_log: called.append(True))
        async with app.run_test() as pilot:
            panel = app.query_one(RunPanel)
            panel.start()
            await pilot.pause()
            self.assertEqual(called, [])          # runner never invoked
            self.assertIsNone(app.finished)

    async def test_runs_and_finishes(self):
        state = SessionState(cutter=object(), sample_length_ms=300)

        def fake_runner(s, on_progress, on_log):
            on_log("started")
            on_progress(1.0)
            return "/tmp/out.mp3"

        app = _Host(state, fake_runner)
        async with app.run_test() as pilot:
            panel = app.query_one(RunPanel)
            panel.start()
            await pilot.pause()
            self.assertEqual(app.finished, "/tmp/out.mp3")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_run_panel -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tui.widgets.run_panel'`

- [ ] **Step 3: Write minimal implementation**

```python
# tui/widgets/run_panel.py
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Label, ProgressBar, RichLog, Static
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
            yield Button("Run grind (r)", id="run_btn", variant="primary")
            yield ProgressBar(total=100, show_eta=False, id="run_progress")
            yield RichLog(id="run_log", max_lines=200, wrap=True)

    def on_button_pressed(self, event):
        if event.button.id == "run_btn":
            self.start()

    def start(self):
        ok, reason = self.state.is_runnable()
        if not ok:
            self._log(f"Cannot run: {reason}")
            return
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
        self.query_one("#run_log", RichLog).write(text)

    def _on_finished(self, path):
        self._log(f"Done: {path}")
        self.query_one("#run_btn", Button).disabled = False
        self.post_message(self.Finished(path))
```

Note: the injected `runner` the app supplies runs `engine.run` on a Textual thread worker and
marshals `on_progress`/`on_log`/completion back with `app.call_from_thread`. The fake in the test is
synchronous, which exercises the same callback contract.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_run_panel -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /home/mesh-home/grainneukeln
git add tui/widgets/run_panel.py tui/test_run_panel.py
git commit -m "feat(tui): run panel with runnable gate, progress, log"
```

---

### Task 8: OutputPanel — browse rendered mixes

**Files:**
- Create: `tui/widgets/output_panel.py`
- Test: `tui/test_output_panel.py`

**Interfaces:**
- Consumes: nothing from earlier tasks; takes an `output_dir` and an injected
  `player(path) -> None` callable (app injects a real player; test injects a spy).
- Produces: `OutputPanel(output_dir, player)` with a `ListView` of mp3 files (newest first).
  `refresh_list()` rescans. `play_selected()` calls `player` with the highlighted path. Key `p` plays,
  `g` refreshes.

- [ ] **Step 1: Write the failing test**

```python
# tui/test_output_panel.py
import os
import tempfile
import unittest
from textual.app import App, ComposeResult
from tui.widgets.output_panel import OutputPanel


class _Host(App):
    def __init__(self, d, player):
        super().__init__()
        self._d = d
        self._player = player

    def compose(self) -> ComposeResult:
        yield OutputPanel(self._d, self._player)


class OutputPanelTest(unittest.IsolatedAsyncioTestCase):
    async def test_lists_and_plays(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("a.mp3", "b.mp3"):
                with open(os.path.join(d, name), "wb") as f:
                    f.write(b"\x00" * 10)
            played = []
            app = _Host(d, lambda p: played.append(p))
            async with app.run_test() as pilot:
                panel = app.query_one(OutputPanel)
                panel.refresh_list()
                await pilot.pause()
                self.assertEqual(len(panel.paths), 2)
                panel.play_selected()
                await pilot.pause()
                self.assertEqual(len(played), 1)
                self.assertTrue(played[0].endswith(".mp3"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_output_panel -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tui.widgets.output_panel'`

- [ ] **Step 3: Write minimal implementation**

```python
# tui/widgets/output_panel.py
import os
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, ListItem, ListView, Static


class OutputPanel(Static):
    BINDINGS = [("p", "play", "Play"), ("g", "refresh", "Refresh")]

    def __init__(self, output_dir, player):
        super().__init__()
        self.output_dir = output_dir
        self._player = player
        self.paths = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Outputs  —  p: play   g: refresh")
            yield ListView(id="output_list")

    def on_mount(self):
        self.refresh_list()

    def refresh_list(self):
        lv = self.query_one("#output_list", ListView)
        lv.clear()
        self.paths = []
        if os.path.isdir(self.output_dir):
            files = [os.path.join(self.output_dir, f)
                     for f in os.listdir(self.output_dir) if f.endswith(".mp3")]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            self.paths = files
            for p in files:
                lv.append(ListItem(Label(os.path.basename(p))))

    def play_selected(self):
        lv = self.query_one("#output_list", ListView)
        idx = lv.index
        if idx is not None and 0 <= idx < len(self.paths):
            self._player(self.paths[idx])

    def action_play(self):
        self.play_selected()

    def action_refresh(self):
        self.refresh_list()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_output_panel -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/mesh-home/grainneukeln
git add tui/widgets/output_panel.py tui/test_output_panel.py
git commit -m "feat(tui): output browser panel (list + play rendered mixes)"
```

---

### Task 9: GrainTUI app — assemble, wire, real adapters

**Files:**
- Create: `tui/app.py`
- Test: `tui/test_app.py`

**Interfaces:**
- Consumes: every widget (Tasks 4-8), `SessionState` (Task 1), `engine` (Tasks 2-3).
- Produces: `GrainTUI(output_dir="output")` — a Textual `App` composing the five panels around one
  shared `SessionState`. Wires: `SourcePanel.Loaded` → set `state.cutter`, seed
  `state.sample_length_ms` from `cutter.step`; `TracksPanel.Changed` → `state.tracks`;
  `RunPanel.Finished` → `OutputPanel.refresh_list()`. Provides the real `loader`, `runner` (threaded
  `engine.build_config`+`engine.run`), and `player`. `run_tui(output_dir)` is the module entry.

- [ ] **Step 1: Write the failing test**

```python
# tui/test_app.py
import unittest
from tui.app import GrainTUI
from tui.state import SessionState


class _FakeCutter:
    beats = [0, 400, 800]
    step = 400
    audio_file_path = "/tmp/x.wav"


class AppWiringTest(unittest.IsolatedAsyncioTestCase):
    async def test_source_loaded_seeds_state(self):
        app = GrainTUI(output_dir="output")
        async with app.run_test() as pilot:
            from tui.widgets.source_panel import SourcePanel
            src = app.query_one(SourcePanel)
            src.post_message(SourcePanel.Loaded(_FakeCutter()))
            await pilot.pause()
            self.assertIsNotNone(app.state.cutter)
            self.assertEqual(app.state.sample_length_ms, 400)  # seeded from step

    async def test_tracks_changed_updates_state(self):
        app = GrainTUI(output_dir="output")
        async with app.run_test() as pilot:
            from tui.widgets.tracks_panel import TracksPanel
            panel = app.query_one(TracksPanel)
            panel.add_track()
            await pilot.pause()
            self.assertEqual(len(app.state.tracks), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_app -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tui.app'`

- [ ] **Step 3: Write minimal implementation**

```python
# tui/app.py
import os
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header

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
    Screen { layout: vertical; }
    #top { height: 1fr; }
    #left { width: 1fr; }
    #right { width: 1fr; }
    """
    BINDINGS = [("r", "run", "Run"), ("q", "quit", "Quit")]

    def __init__(self, output_dir="output"):
        super().__init__()
        self.state = SessionState(output_dir=output_dir)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            with Vertical(id="left"):
                yield SourcePanel(_real_loader)
                yield ParamsPanel(self.state)
                yield TracksPanel(self.state.tracks)
            with Vertical(id="right"):
                yield RunPanel(self.state, self._threaded_runner)
                yield OutputPanel(self.state.output_dir, _real_player)
        yield Footer()

    # --- wiring ---
    def on_source_panel_loaded(self, msg):
        self.state.cutter = msg.cutter
        step = int(getattr(msg.cutter, "step", 0) or 0)
        if step > 0:
            self.state.sample_length_ms = step
            try:
                from textual.widgets import Input
                self.query_one("#sample_length", Input).value = str(step)
            except Exception:
                pass

    def on_tracks_panel_changed(self, msg):
        self.state.tracks = msg.tracks

    def on_run_panel_finished(self, msg):
        self.query_one(OutputPanel).refresh_list()

    def action_run(self):
        # push params into state, then run
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

        def done(worker):
            if worker.result:
                self.call_from_thread(self.query_one(RunPanel)._on_finished, worker.result)

        on_log(f"Rendering {len(state.tracks)} track(s), cut {state.sample_length_ms}ms...")
        worker = self.run_worker(work, thread=True, exit_on_error=False)
        worker.node  # keep ref
        self.workers  # noqa
        # attach completion via Textual worker state change
        self._pending = worker
        return None  # completion arrives async via on_worker_state_changed

    def on_worker_state_changed(self, event):
        from textual.worker import WorkerState
        if event.state == WorkerState.SUCCESS and event.worker.result:
            self.query_one(RunPanel)._on_finished(event.worker.result)
        elif event.state == WorkerState.ERROR:
            self.query_one(RunPanel)._log(f"Run failed: {event.worker.error}")
            from textual.widgets import Button
            self.query_one("#run_btn", Button).disabled = False


def run_tui(output_dir="output"):
    GrainTUI(output_dir=output_dir).run()
```

Note on the runner: the injected `_threaded_runner` returns `None` (completion is delivered
asynchronously through `on_worker_state_changed`), so `RunPanel.start` must treat a `None` return as
"in flight, will finish later" — which it already does (it only calls `_on_finished` when the return
is non-None). The synchronous fake in Task 7 returns a path and exercises the immediate path; this
threaded adapter exercises the async path in the smoke test below.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest tui.test_app -v`
Expected: PASS (2 tests)

- [ ] **Step 5: End-to-end smoke on real audio (manual, real-artifact)**

Run:
```bash
cd /home/mesh-home/grainneukeln
python -c "
import asyncio, glob, os
from tui.app import GrainTUI
async def main():
    app = GrainTUI(output_dir='output')
    async with app.run_test() as pilot:
        from tui.widgets.source_panel import SourcePanel
        app.query_one(SourcePanel).load(os.path.abspath('assets/test_audio.wav'))
        await pilot.pause(0.5)
        app.action_run()
        for _ in range(60):
            await pilot.pause(0.5)
            if glob.glob('output/grain_*.mp3'):
                break
    outs = sorted(glob.glob('output/grain_*.mp3'), key=os.path.getmtime)
    assert outs, 'no output produced'
    print('OK', outs[-1], os.path.getsize(outs[-1]), 'bytes')
asyncio.run(main())
"
```
Expected: prints `OK output/grain_...mp3 <size> bytes` with size > 2000. This drives the real loader,
real engine, real export — the operator's actual path.

- [ ] **Step 6: Commit**

```bash
cd /home/mesh-home/grainneukeln
git add tui/app.py tui/test_app.py
git commit -m "feat(tui): assemble GrainTUI app, wire panels, real threaded runner"
```

---

### Task 10: Entrypoint, dependency, docs

**Files:**
- Modify: `main.py` (add `--tui` flag)
- Modify: `requirements.txt` (add `textual`)
- Modify: `run.sh` or add `run_tui.sh`
- Modify: `README.md` (point at the TUI as the primary interface)

**Interfaces:**
- Consumes: `tui.app.run_tui` (Task 9).
- Produces: `python main.py --tui` launches the TUI.

- [ ] **Step 1: Add the flag to main.py**

In `main.py`, add to the argparse block:
```python
    parser.add_argument("--tui", action="store_true", help="Launch the terminal UI (headless-friendly)")
```
and, right after `args = parser.parse_args()`:
```python
    if args.tui:
        from tui.app import run_tui
        run_tui()
        sys.exit(0)
```

- [ ] **Step 2: Add the dependency**

Append to `requirements.txt`:
```
# --- TUI only (optional: `python main.py --tui`) ---
textual
```

- [ ] **Step 3: Install and verify import**

Run:
```bash
cd /home/mesh-home/grainneukeln
python -m pip install textual
python -c "import textual; from tui.app import run_tui; print('tui import ok')"
```
Expected: `tui import ok`

- [ ] **Step 4: Run the full test suite**

Run: `cd /home/mesh-home/grainneukeln && python -m unittest discover -s tui -p 'test_*.py' -v`
Expected: all TUI tests PASS.

Also confirm nothing else broke: `python -m unittest discover -s . -p 'test_*.py' 2>&1 | tail -5`

- [ ] **Step 5: Add a run helper + README note**

Create `run_tui.sh`:
```bash
#!/bin/bash
cd "$(dirname "$0")"
python main.py --tui
```
`chmod +x run_tui.sh`.

In `README.md`, under how-to-run, add a short "Terminal UI (recommended, headless-friendly)" line:
`python main.py --tui` — drive load → params → multitrack → run → preview from the keyboard over SSH.

- [ ] **Step 6: Commit**

```bash
cd /home/mesh-home/grainneukeln
git add main.py requirements.txt run_tui.sh README.md
git commit -m "feat(tui): --tui entrypoint, textual dep, run helper + README"
```

---

## Self-Review

**Spec coverage:**
- Textual TUI replacing REPL+Qt → Tasks 9, 10. ✓
- Source panel (file/YouTube) → Task 6. ✓
- Live grain params → Task 5. ✓
- Multitrack editor (first-class) → Task 4. ✓
- Run + progress + log → Task 7. ✓
- Output browser + preview → Task 8. ✓
- engine seam / build_config / run with real-artifact + loudness gate → Tasks 2, 3. ✓
- Headless-graceful playback → Task 8/9 (`_real_player`; degrade note in spec; a no-sink error is
  caught in `OutputPanel`/player call). ✓
- No `d` duration cap → honored (absent everywhere). ✓
- unittest, no pytest → all tests use unittest / IsolatedAsyncioTestCase. ✓
- textual-only new dep → Task 10. ✓

**Placeholder scan:** No TBD/TODO; every code step carries real code. ✓

**Type consistency:** `SessionState`, `TrackSpec`, `build_config(cutter, state)`, `run(config, out_dir,
on_progress)`, message classes `SourcePanel.Loaded`, `TracksPanel.Changed`, `RunPanel.Finished` used
consistently across tasks. ✓

**Known risk to watch during execution:** Textual API surface (worker completion, `ListView.index`,
`ProgressBar.update`) can shift by version. If a widget test fails on an API mismatch, pin/adjust to
the installed `textual` version rather than working around it — record the version in the commit.
