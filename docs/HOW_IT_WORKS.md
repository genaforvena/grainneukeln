# grainneukeln — how it works (and why it hallucinates rhythm)

The [README](../README.md) is the quick tour. This doc is the longer story: **what the instrument's
character actually is**, the measured proof of it, the step-by-step pipeline, and the performance
numbers. If you want the code-level machinery of each mixer, that's [`ALGORITHMS.md`](ALGORITHMS.md);
if you want every knob, that's [`PARAMETERS.md`](PARAMETERS.md).

---

## What it *is*: a rhythm-seeking maniac

The mechanics are only half the story. The other half is its **character**, and it explains most of
what you'll hear.

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

## The pipeline, step by step

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

> Every export is loudness-normalized (RMS to −16 dBFS, capped at a −1 dBFS true peak so the encode
> never clips) — raw automixes are near-inaudible otherwise. Tunable via `GRAINNEUKELN_TARGET_DBFS` /
> `GRAINNEUKELN_PEAK_DBFS`.

The four mixer modes (`rw` / `q` / `poly` / `lib`) are distinct algorithms, not presets — each
selects and places grains differently. For the code-level treatment — the euclidean (Bjorklund)
generator, the polyrhythm phasing math, the feature-clustering + Markov sequencing in `lib`,
beat-clock derivation, the loudness stage, and the determinism note — see
[`ALGORITHMS.md`](ALGORITHMS.md).

---

## Performance

The automixer's concat/overlay is **O(n)** in output length (refactored 2026-07-19 from the original
O(n²) pattern). The dominant cost is the per-grain band-pass filter, and only when you opt into it
with `c low,high`:

**Speed comparison (30s source, measured 2026-07-19):**

| mode | BPF-on (explicit `c`) | BPF-off (default) | speedup |
|------|----------------------|-------------------|---------|
| rw   | 27.4s                | 6.0s              | 4.6×    |
| q    | 2.75s                | 0.82s             | 3.4×    |
| poly | 5.65s                | 1.23s             | 4.6×    |
| lib  | 2.64s                | 0.62s             | 4.3×    |

**Recommendation:** use the default (no `c` arg) for fast iteration and exploration. Opt into
explicit `c low,high` bands when you want the filtered character or multi-band layering. Short clips
(a few seconds) render in milliseconds on either path.
