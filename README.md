# grainneukeln — a granular sampler

**In one breath:** give it audio you already have — a song, a field recording, a voice memo — and it
rebuilds it into *new* audio. It slices the sound into tiny **grains** lined up to the beat, then
stitches those grains back together in a shuffled, re-filtered order. The result keeps the original's
pulse and texture but becomes something new — hypnotic, glitchy, remixed. That's **granular
resynthesis**, driven by the source's own rhythm.

Two runs with the same settings give two different tracks (grain picks are random) — but both stay
locked to the source's groove.

---

## How it works

What actually happens when you run an automix:

1. **Find the beat.** The track is analysed into a list of beat positions (milliseconds). Everything
   downstream is anchored to these beats — the rhythm of the source becomes the skeleton of the output.
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
| `l`  | grain length | `l /2`, `l *3`, `l 250` | `/` or `*` scales the beat-derived default; a bare number sets milliseconds. Shorter = finer, more fragmented texture. |
| `s`  | whole-mix speed | `s 0.8` | tempo of the **final** track (pitch preserved). `<1` slower, `>1` faster. |
| `ss` | per-grain speed | `ss 1.2` | tempo of **each grain** (pitch preserved) — warps the micro-texture. |
| `c`  | channels / bands | `c 0,250;250,15000` | one or more `low,high` band-pass bands in Hz, separated by `;`. Each band pulls its **own** random grain and they're layered — e.g. split bass and treble into independent grain streams. |
| `w`  | window divider | `w 4` | windows = `total_beats / w`. Bigger `w` → smaller windows → grains drawn from tighter time-neighborhoods (more local, less wandering). |
| `m`  | mode | `m rw` | grain-selection algorithm. `rw` (random window) is the tested default. |

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

## GUI

`python main.py` with no arguments launches the PySide6 GUI: load from file or YouTube, detect beats,
configure and run the automixer, play and save. (GUI extras: `PySide6`, `pyqtgraph`.)

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
