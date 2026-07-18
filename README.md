# grainneukeln — a granular sampler

**In one breath:** give it audio you already have — a song, a field recording, a voice memo — and it
rebuilds it into *new* audio. It slices the sound into tiny **grains** lined up to the beat, then
stitches those grains back together in a shuffled, re-filtered order. The result keeps the original's
pulse and texture but becomes something new — hypnotic, glitchy, remixed. That's **granular
resynthesis**, driven by the source's own rhythm.

Two runs with the same settings give two different tracks (grain picks are random) — but both stay
locked to the source's groove.

---

## What it *is*: a rhythm-seeking maniac

The mechanics below are only half the story. The other half is its **character**, and it explains
most of what you'll hear:

**It sees rhythm everywhere — including where there is none.** Beat detection doesn't *ask* whether
the audio is rhythmic. It fits a pulse to whatever fluctuation it can find, and it always has a
default tempo in mind (librosa's prior, ~120 BPM). Hand it a beatless field recording, room hum, or
literal white noise, and it will not shrug — it will hear a beat and commit to it:

| what you feed it | what it "hears" |
|---|---|
| white noise (no rhythm whatsoever) | **23 beats, 112 BPM** — a confident pulse, invented |
| 8 real room recordings (ambient hum, no music) | **15–53 beats each; median 123.0 BPM** (range 80.7–184.6) — it never once said "no rhythm here" |
| a real 400 ms click track | **400.1 ms** — dead accurate, when the rhythm is genuinely there |
| a steady drone, or digital silence | *nothing* (0 beats) — it needs some flutter to latch onto |

*(Measured, not asserted — `librosa.beat.beat_track` on real captures, 2026-07-15.)*

So there are two regimes, and it never tells you which one it's in: when a real pulse exists it
locks to it faithfully; when none exists it **hallucinates** one near its 120 BPM prior. Both feel
equally confident downstream. This is not a bug to be fixed — it is the instrument. The imagined
grid is what lets you grind a rainstorm or a room's silence into something that *grooves*.

**Then it cuts everything it hears to fit that rhythm.** Real or imagined, the beat grid becomes the
skeleton: every grain starts on a beat, every window is measured in beats, every chunk is about one
beat long. Nothing survives off-grid. Whatever went in comes out marching.

**And subdividing the grid doesn't break it.** `l /2`, `l /3`, `l *2`, `l *3` scale the grain length
against the beat period by **integer ratios** — so the grains stay metrically coherent with the
pulse it imagined. A grain of `T/3` still lands on the grid every third grain; the *felt* rhythm of
the original (real or invented) is preserved while the texture changes completely. That's why `/3`
sounds like a new reading of the same groove rather than a different tempo: you're re-reading the
grid, not moving it. Change `s` if you want to actually move it.

> Practical upshot: **beatless input is not a failure mode, it's a use case** — but check the beat
> count. A source with 0 detected beats gives the grinder nothing to build on and yields an empty or
> dead mix. Anything with a few beats — real or hallucinated — will grind.

---

## How it works

What actually happens when you run an automix:

1. **Find the beat — or invent one.** The track is analysed into a list of beat positions
   (milliseconds) via `librosa.beat.beat_track`. Everything downstream is anchored to these beats:
   the rhythm of the source becomes the skeleton of the output. Note that this step *cannot fail
   loudly* — given any fluctuating audio it returns a grid, whether or not the source has a pulse
   (see [rhythm-seeking maniac](#what-it-is-a-rhythm-seeking-maniac)). Only a featureless drone or
   silence returns nothing.
2. **Slide a window over the beats.** Rather than look at the whole track at once, a *rolling window*
   moves across the beat list. Its size is `total_beats / window_divider`, so a bigger `w` means a
   smaller, tighter window — grains get drawn from a narrower slice of time.
3. **Fill each window with grains.** For every window it builds a chunk:
   - pick a **random** beat inside the window as the grain's start point,
   - cut a grain `l` milliseconds long from there,
   - run it through a **band-pass filter** for each channel (keep only chosen frequency bands),
   - layer the channels on top of each other,
   - repeat, appending grains, until the chunk is about one beat long.
4. **Optionally bend time.** Each grain can be sped up / slowed (`ss`), and the finished mix as a whole
   can be sped up / slowed (`s`) — pitch-preserving time-stretch.
5. **Concatenate.** All the window-chunks are joined end to end → your new track (MP3, optionally WAV).

```
source audio
  │  detect beats  →  ● ● ● ● ● ● ● ● ● ● ● ●      beat positions (ms)
  │  rolling window   └──[ window ]──┘              size = beats / w
  │                        ├ pick a RANDOM grain start inside the window
  │                        ├ cut a grain (length l)
  │                        ├ band-pass per channel (c)  → layer them
  │                        └ optional per-grain speed (ss)
  │  …one chunk per window, each ~one beat long…
  ▼
new track  =  chunk₁ + chunk₂ + chunk₃ + …          (+ optional whole-mix speed s)
```

---

## Install (Python 3.12+, no Conda)

```bash
uv venv .venv && . .venv/bin/activate     # or: python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt           # GUI extras are optional
# system prerequisite: ffmpeg  (pydub uses it for mp3/m4a/webm)
```

Beat detection and time-stretch use **librosa** — no `madmom`/`rubberband` build needed
(see [PR #3](https://github.com/genaforvena/grainneukeln/pull/3)). The Conda flow still works but
isn't required.

---

## Use it (command line)

```bash
python main.py <audio file or YouTube URL> <output dir> [automix params]
```

```bash
# default automix
python main.py song.mp3 output/

# half-length grains, each grain a touch faster, whole mix a touch slower
python main.py song.mp3 output/ amc l /2 ss 1.2 s 0.9

# two frequency bands (bass + air), tighter windows
python main.py song.mp3 output/ amc c 1,250;10000,15000 w 6
```

### Automix parameters — the `amc` block

| param | meaning | example | what it does |
|-------|---------|---------|--------------|
| `l`  | grain length | `l /2`, `l *3`, `l 250` | `/` or `*` scales the beat-derived default by an **integer ratio**, so the grain stays metrically coherent with the detected (or imagined) pulse — `/3` re-reads the same groove rather than moving it. A bare number sets milliseconds outright, which is the one way to cut *against* the grid. Shorter = finer, more fragmented texture. |
| `s`  | whole-mix speed | `s 0.8` | tempo of the **final** track (pitch preserved). `<1` slower, `>1` faster. |
| `ss` | per-grain speed | `ss 1.2` | tempo of **each grain** (pitch preserved) — warps the micro-texture. |
| `c`  | channels / bands | `c 0,250;250,15000` | one or more `low,high` band-pass bands in Hz, separated by `;`. Each band pulls its **own** random grain and they're layered — e.g. split bass and treble into independent grain streams. |
| `w`  | window divider | `w 4` | windows = `total_beats / w`. Bigger `w` → smaller windows → grains drawn from tighter time-neighborhoods (more local, less wandering). |
| `m`  | mode | `m rw`, `m q`, `m poly`, `m lib` | grain-selection algorithm. `rw` (random window) is the tested default; `q` quantized, `poly` polyrhythmic, `lib` feature-library (all below). |
| `lib` `lk` | library policy / clusters (mode `lib`) | `lib con lk 8` | `lib sim`/`lib con` selects the sequencing policy (similarity vs contrast); `lk` sets the cluster count. Only used by `m lib`. |
| `snap` | snap-to-beat | `snap` | pitch-preserving time-stretch of each grain to land exactly in its slot (composable, any mode). Off by default. |
| `sw` | swing % | `sw 66` | micro-timing groove: delay every off-beat grain. `0`/`<=50` = straight (no-op), `66` = 2:1 shuffle. |
| `ek` `en` | euclidean pattern (mode `q`) | `ek 3 en 8` | `E(k, n)`: place `k` grains across `n` beat-subdivision slots as an evenly-spread euclidean rhythm. `E(3,8)` is the tresillo, `E(5,8)` the cinquillo, `E(4,4)` four-on-the-floor. Only used by `m q`. |
| `pr` | poly streams (mode `poly`) | `pr 4;3`, `pr 4:1-2000;3:6000-15000` | `ratio[@length][:low-high]` stream specs separated by `;`. Each stream fires `ratio` grains per beat; `4;3` is a 3-against-4 polyrhythm. Optional per-stream grain length (ms) and band-pass. Only used by `m poly`. |

#### Quantized mode (`m q`) — designed grooves instead of a uniform fill

`rw` picks a random beat per grain and concatenates — the groove is whatever the source had. `q`
subdivides the beat period into `n` slots and fires a grain **only on the slots a euclidean pattern
`E(k, n)` marks**, cutting each grain at a source **onset** snapped to the grid. The output has a
*designed* rhythm (tresillo, cinquillo, …) laid over the source's transients. Two runs differ in grain
content but the **grid placement is deterministic** given the pattern. Beatless input still grinds on
the hallucinated grid (no beat floor — same rhythm-seeking regime as `rw`).

```bash
python main.py song.mp3 output/ amc m q ek 3 en 8      # tresillo
python main.py song.mp3 output/ amc m q ek 5 en 8 ss 1.5   # cinquillo, grains sped up
```

#### Polyrhythmic mode (`m poly`) — N phasing grain streams (Reich-style)

`rw`/`q` run a **single** stream (one grain at a time). `poly` runs **N parallel streams** at
different subdivisions of the same beat grid and **overlays** them, so they phase against each other
(Steve Reich's "Piano Phase", but granular). A stream at `ratio` r fires r grains per beat; two
streams at 4 and 3 give a **3-against-4** polyrhythm that coincides every `LCM(3,4)=12` subdivisions
and drifts out of phase in between. Each stream keeps its own grain length and band-pass, so the
layers stay distinguishable. Beatless input still grinds on the hallucinated grid.

```bash
python main.py song.mp3 output/ amc m poly pr 4;3                 # 3-against-4, full band
python main.py song.mp3 output/ amc m poly pr 4:1-2000;3:6000-15000   # split low vs high band
python main.py song.mp3 output/ amc m poly pr 4@80:1-2000;3@120:6000-15000  # staccato, per-stream length
```

#### Library mode (`m lib`) — sequenced selection instead of random

Every other mode picks grains at random (memoryless). `lib` first builds a **library** of beat-grid
grains, measures each on three axes — spectral centroid, RMS, and rhythm-density (onsets/sec) —
**rank-calibrated against the actual grain set** (so no axis can saturate), clusters them, and then
**sequences** grains with a Markov policy over the clusters:

- `lib sim` (**similarity**) — stay in / near the current cluster → hypnotic, coherent.
- `lib con` (**contrast**) — jump to a distant cluster → jarring, glitchy.

The two policies produce measurably different grain-to-grain motion. Too few grains to cluster degrades
honestly (reported), it does not fake a full clustering.

```bash
python main.py song.mp3 output/ amc m lib sim lk 6     # coherent, stays in-cluster
python main.py song.mp3 output/ amc m lib con lk 8     # glitchy, jumps between clusters
```

#### Snap-to-beat + swing (`snap`, `sw`) — composable placement effects

Two small effects usable by any mode. **Snap** (`snap`) pitch-preservingly time-stretches each grain so
off-length material lands *exactly* in its beat slot instead of smearing the groove. **Swing** (`sw`)
applies a micro-timing offset so the output breathes instead of marching: `sw 66` is a 2:1 shuffle,
`sw 0` (or `<=50`) is a genuine no-op (bit-identical straight placement).

```bash
python main.py song.mp3 output/ amc m q ek 3 en 8 snap sw 66   # tresillo, snapped, shuffled
python main.py song.mp3 output/ amc snap                       # snap composed onto the rw baseline
```

### Interactive shell

Run **without** automix params to drop into an interactive cutter
(`python main.py song.mp3 output/`):

| command | does |
|---------|------|
| `p` | play the current selection |
| `b <ms>` / `l <ms>` | set selection start / length |
| `s <ms>` | set the step size for `f`/`r` |
| `f` / `r` | step forward / rewind (repeat the letter to go further: `fff`) |
| `cut` / `cut -a` | export the current selection (`-a` snaps to a nearby amplitude peak) |
| `autocut [n]` | export many cuts automatically |
| `am` | automix the whole track |
| `amc …` / `amc info` | set automix params / show the current config |
| `load <file>` | load a different track |
| `plot` / `info` | view amplitude / current settings |
| `set_wav_enabled` / `set_wav_disabled` | also export WAV alongside MP3 |
| `help` / `q` | help / quit |

---

## TUI (recommended, headless-friendly)

```
python main.py --tui
```

A keyboard-driven terminal UI you can run over SSH inside tmux — no display server needed. One screen:
load a source (file path or YouTube URL), edit the grain params live (speed, sample-speed, window
divider, sample length), manage the **multitrack** channel bands as track rows (`a` add, `d` remove,
`enter` edit each track's low/high Hz), run the grind with a progress bar + log (`r`), and browse /
preview the rendered mixes. TUI extra: `textual`. This is the primary interface; the Qt GUI below
stays for desktop use.

---

## GUI

`python main.py` with no arguments launches the PySide6 GUI: load from file or YouTube, detect beats,
configure and run the automixer, play and save. (GUI extras: `PySide6`, `pyqtgraph`.) Needs a display
server — on a headless box use the TUI above.

---

## Performance note

The automixer's band-pass + segment-append is pure Python and roughly **O(n²)** in track length, so a
full 3-minute song takes a while. Feed it **short clips** (a few seconds) for fast, responsive
remixes — which also fits live/ambient-capture use.

---

## Docker

```bash
./run_granular_sampler.sh
```

Builds the image and runs the container with settings for your OS. Windows users may need an X server
(e.g. VcXsrv) for the GUI.

## Contributing

Contributions welcome — please open a Pull Request.
