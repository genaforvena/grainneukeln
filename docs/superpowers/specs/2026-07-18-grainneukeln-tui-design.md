# grainneukeln TUI — design

**Date:** 2026-07-18
**Status:** approved (operator, via Telegram)
**Branch:** `feat/tui-interface`

## Context & problem

grainneukeln is a granular rolling-window resynthesizer. Today it has two front-ends:

1. A **raw REPL** (`cutter/sample_cut_tool.py::SampleCutter.run`) — a bare `>>>` prompt of terse
   single-letter commands (`b`, `l`, `s`, `amc …`, `am`, `p`, `cut`). No visible state, no live
   parameter view, help only on demand. Hard to drive, easy to mis-type.
2. A **PySide6/Qt GUI** (`main_window.py`, `main.py --gui`) — needs a display server. The primary
   node this runs on (mesh-home) is **headless**, so the GUI is dead weight there.

The operator asked (2026-07-18) for "a proper TUI" — a terminal UI drivable over SSH inside tmux —
**and** that the tool's existing **multitrack** capability live there too, first-class.

"Multitrack" already exists as `AutoMixerConfig.channels_config`: a list of `ChannelConfig(low, high)`
band-pass tracks. `RandomWindowAutoMixer._create_chunk` iterates them — each track pulls its **own**
random grain from the current window, band-pass filters it to its frequency range, and `overlay`s it
onto the chunk. In the REPL this is one cramped field: `c 1,250;251,400;10000,15000`. It deserves a
real editor.

## Goals

- A **Textual** TUI, one screen, keyboard-driven, that runs headless over SSH/tmux.
- Replaces **both** the REPL and the Qt GUI as the human front-end (they stay in the repo; the TUI
  becomes the documented way in).
- Surfaces the full parameter model live: source, speed, sample-speed, window-divider, sample-length,
  and the **multitrack** track list.
- A proper **multitrack editor**: tracks as rows, each with a low/high Hz range, add/remove/edit from
  the keyboard, with the count and ranges always visible.
- Load a source (local file **or** YouTube URL), show detected beats/tempo/derived step.
- Run the grind with a live progress indicator + log, then let the user preview and browse outputs.

## Non-goals (YAGNI)

- No waveform/spectrogram rendering (the Qt path had matplotlib/pyqtgraph; a TUI plot is scope creep
  and the operator didn't ask). Beat/tempo **numbers** are enough.
- No new DSP or mixer modes. Only `rw` exists and is the only tested mode; the TUI exposes what the
  engine already does, it does not extend it.
- No editing of already-rendered outputs. The output browser plays and reveals paths; it does not
  re-mix in place.
- No mouse-first design. Mouse works (Textual gives it free) but every action has a key.
- **No duration cap in v1.** `run_with_params.sh` passes `d 60` as if it caps mix length, but
  `config_automix` never parses `d` — the flag is silently dropped today, a phantom. Rather than
  propagate a fake field, it's deferred; adding it later is a trivial engine-side truncation
  (`mix[: d*1000]`), and it is NOT an existing capability to "surface".

## Architecture

A thin **Textual** app that drives the **existing** engine objects unchanged — `SampleCutter`,
`AutoMixerConfig`, `AutoMixerRunner`. The TUI is a view/controller; the DSP core is untouched.

```
tui/
  app.py            GrainTUI(App)      — layout, key bindings, wiring, run orchestration
  state.py          SessionState       — plain dataclass: source path, cutter, params, last output
  widgets/
    source_panel.py    SourcePanel     — load file / paste YouTube URL; shows loaded path + beats/tempo
    params_panel.py    ParamsPanel     — speed, sample_speed, window_divider, sample_length, duration
    tracks_panel.py    TracksPanel     — the multitrack editor (channel rows)
    run_panel.py       RunPanel        — Run button, progress, scrolling log
    output_panel.py    OutputPanel     — list of rendered mixes; play / reveal path
  engine.py         adapter: build AutoMixerConfig from SessionState, run in a worker thread,
                    export the mix; wraps the existing runner + export path.
main entry:         `python main.py --tui`  (and a `grain-tui` convenience via run.sh)
```

Textual's `run_worker(..., thread=True)` runs the (blocking, CPU-bound) load and mix off the UI
thread so the interface stays responsive; progress is pushed back via `post_message`.

### Parameter model (authoritative — mirrors `AutoMixerConfig`)

| TUI field            | DSL | type / range                        | default                | notes |
|----------------------|-----|-------------------------------------|------------------------|-------|
| speed                | `s` | float, 0.1–10.0                     | 1.0                    | whole-track tempo multiplier (post-mix) |
| sample_speed         | `ss`| float, 0.1–10.0                     | 1.0                    | per-grain tempo |
| window_divider       | `w` | int, 1–10                           | 2                      | rolling-window subdivision |
| sample_length (ms)   | `l` | int > 0                             | beat-derived step      | seeded from detected step on load |
| mode                 | `m` | fixed `rw`                          | rw                     | only tested mode; shown read-only |
| tracks (multitrack)  | `c` | list of (low Hz, high Hz)           | one track: 0,15000     | the editor below |
| wav export           | —   | bool                                | off                    | mirrors `is_wav_export_enabled` |

The TUI holds these as typed fields in `SessionState`; `engine.build_config()` constructs the
`AutoMixerConfig` directly (bypassing the string DSL — no round-trip through `amc` parsing, so no
mis-quoting). The `amc` string is still shown read-only as a "recipe" line for copy/paste parity with
the REPL and the sound-reflex logs.

## Components

**SourcePanel** — *what:* choose and load a source. *Interface:* a path input (with a file-browser
key) and a URL input; on submit it loads via `SampleCutter` (YouTube URLs route through the existing
`youtube.downloader`). Emits `SourceLoaded(cutter)`. *Depends on:* `SampleCutter`, `youtube.downloader`.
Shows: loaded filename, detected beat count, tempo (BPM), derived step (ms).

**ParamsPanel** — *what:* edit the scalar grain params (speed, sample_speed, window_divider,
sample_length). *Interface:* labelled numeric inputs bound to `SessionState`; validates ranges on
change, refuses out-of-range with an inline hint. Emits `ParamsChanged`. *Depends on:* nothing but
`SessionState`.

**TracksPanel (multitrack editor)** — *what:* manage the channel/track list. *Interface:* a
`DataTable` of rows `# | low Hz | high Hz`; keys: `a` add track (defaults to full-band, editable),
`d`/`delete` remove selected, `enter` edit low/high of selected. Validates `0 ≤ low < high`. Always
shows the track count. Emits `TracksChanged`. *Depends on:* `ChannelConfig`. This is the first-class
home for the tool's multitrack.

**RunPanel** — *what:* trigger and observe a grind. *Interface:* `Run` (key `r`) builds the config
from state, spawns the engine worker, streams progress into a bar and the last-N log lines; on finish
shows the output path + elapsed. Disabled while running. *Depends on:* `engine`.

**OutputPanel** — *what:* browse rendered mixes. *Interface:* a list of files under the session output
dir (newest first), with `p` play (via `pydub.playback` / system player, degrade gracefully when
headless with no audio sink — show the path to copy) and `o` reveal path. *Depends on:* filesystem +
optional playback.

**engine.py** — *what:* the one seam between TUI and DSP. `build_config(state) -> AutoMixerConfig`;
`run(config, out_dir, on_progress) -> Path`. Wraps `AutoMixerRunner().run` + the existing export
(loudness-normalized, per `fix/export-loudness-normalization`). Pure, testable without Textual.

## Data flow

1. User loads a source → `SampleCutter` decodes + librosa beat-detects → `SessionState.cutter`,
   `sample_length` seeded from the derived step; SourcePanel shows beats/tempo.
2. User edits params + tracks → typed writes into `SessionState` (no string DSL in the loop).
3. `Run` → `engine.build_config(state)` → worker thread `AutoMixerRunner().run` → export to
   `output/<stamp>.mp3` → OutputPanel refreshes; RunPanel shows path + elapsed.
4. Preview from OutputPanel; iterate params and re-run.

## Error handling

- **Load failures** (missing/empty/undecodable file, YouTube download error, zero beats detected):
  caught at the panel, shown as an inline error line; the app stays up. Zero beats → explain the
  source is too steady/silent to latch a pulse (the engine needs flutter), don't crash.
- **Invalid params:** rejected at input with an inline hint; `Run` is gated on a valid state
  (source loaded + at least one track + all ranges valid) and greys out otherwise.
- **Mix failure** (exception in the worker, OOM, empty mix): surfaced in the run log with the message;
  no partial/silent file is presented as success — if export produced nothing or a near-silent file,
  say so (this repo has a history of silent-fallback mixes; the panel asserts a non-trivial output
  size and flags if it's suspiciously small).
- **Headless with no audio sink:** preview degrades to "can't play here — path: …" rather than
  throwing. The TUI itself never needs an audio device.

## Testing

- **engine.py unit tests** (no Textual): `build_config` maps a `SessionState` to the right
  `AutoMixerConfig` (each field + multi-track list → matching `channels_config`); `run` against the
  bundled `assets/test_audio.wav` produces a non-empty, non-silent mp3 (assert file size and a
  loudness floor — guards the silent-fallback failure mode). This is the real-artifact gate.
- **Widget logic tests** via Textual's `App.run_test()` pilot: adding/removing tracks changes the
  count and the built config; invalid ranges are rejected; `Run` is gated until state is valid.
- **Manual smoke** over SSH/tmux on mesh-home: load `assets/test_audio.wav`, add a second track,
  run, confirm an audible output file — the operator's real environment.

## Rollout

- Entry point: `python main.py --tui` (parallels the existing `--gui`), plus `run.sh` convenience.
- `requirements.txt` gains a `# --- TUI ---` block: `textual` (and its `rich` dep). The core CLI
  automix path keeps needing nothing new; TUI deps are opt-in like the GUI deps.
- The Qt GUI and REPL remain for now (no removal in this change); README's "how to run" points at the
  TUI as the primary interface. A follow-up may retire the Qt path once the TUI covers it.
