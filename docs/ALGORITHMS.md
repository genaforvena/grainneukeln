# grainneukeln — Mixing Algorithms

A faithful, code-level reference for how grainneukeln turns a source recording into a new track.
Every claim here is traceable to the source; citations are `file:line`.

> **Companion docs:** [`PARAMETERS.md`](PARAMETERS.md) is the complete `amc` parameter reference and
> the cross-mode matrix. The [README](../README.md) is the tour and the philosophy. This file is the
> machinery.

---

## Table of contents

1. [The pipeline](#1-the-pipeline)
2. [Beat detection & the grain clock](#2-beat-detection--the-grain-clock)
3. [The `rw` mixer — random window](#3-the-rw-mixer--random-window)
4. [The `q` mixer — quantized euclidean grid](#4-the-q-mixer--quantized-euclidean-grid)
5. [The `poly` mixer — phasing polyrhythm](#5-the-poly-mixer--phasing-polyrhythm)
6. [The `lib` mixer — measured, clustered, sequenced](#6-the-lib-mixer--measured-clustered-sequenced)
7. [Shared building blocks](#7-shared-building-blocks)
8. [Loudness & export](#8-loudness--export)
9. [Determinism & reproducibility](#9-determinism--reproducibility)

---

## 1. The pipeline

```
source (file / YouTube URL)
   │
   │  librosa.beat.beat_track           cutter/sample_cut_tool.py:113
   ▼
beat positions (ms)  ──►  beat_interval = median inter-beat gap  ──►  sample_length (grain clock)
   │
   │  config_automix() parses the `amc` line into a fresh AutoMixerConfig   :276
   ▼
AutoMixerRunner.run(config)             automixer/runner.py:6
   │   config.mixer().mix(config)        ← one of rw / q / poly / lib
   │   if speed != 1.0: change_audioseg_tempo(mix, speed)   ← GLOBAL final stretch
   ▼
normalize_loudness(mix)                 cutter/sample_cut_tool.py:430
   ▼
export  <orig>___mix_cut<L>-vtgsmlpr____<timestamp>.mp3  (+ optional .wav)
```

Two speed knobs live at two different layers, and this is the single most important thing to
internalize:

- **`ss` (sample_speed)** is applied *inside* each mixer, **per grain**, as the grains are cut. It
  warps micro-texture.
- **`s` (speed)** is applied *once*, in the runner, to the **finished mix** (`runner.py:11-12`). It
  moves the whole track's tempo. It is a post-process, not part of grain selection.

Both use the same pitch-preserving time-stretch (`change_audioseg_tempo`, §7).

The entry point (`main.py:54` → `sample_cut_tool.main`) runs `config_automix(...)` then `automix("am")`
for a one-shot CLI grind, or drops into the interactive REPL when no `amc` line is given
(`cutter/sample_cut_tool.py:267,530`).

---

## 2. Beat detection & the grain clock

Everything downstream is anchored to the source's beats. There is no separate tempo track — the
**beat positions themselves** are the skeleton.

### 2.1 Detection (`_detect_beats`, `cutter/sample_cut_tool.py:113-128`)

```python
y, sr = librosa.load(path, sr=None, mono=True)
_tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
beat_times = librosa.frames_to_time(beat_frames, sr=sr)      # seconds
beat_positions = (np.asarray(beat_times) * 1000).astype(int) # → ms
```

`beat_track`'s scalar tempo is **discarded**. What survives is the ordered list of **cumulative beat
positions in integer milliseconds**. (madmom was removed in favour of librosa — same contract, clean
install; comment `:114-118`.)

**This step cannot fail loudly.** Given any fluctuating audio, `beat_track` returns a grid whether or
not the source has a real pulse — it fits librosa's ~120 BPM prior to whatever it finds. White noise
yields a confident invented grid; a featureless drone or digital silence yields *nothing* (0 beats),
which is the only "no build material" case. See the README's *rhythm-seeking maniac* section for the
measured regimes. Consequence for every mixer below: **there is no beat floor** — beatless input still
grinds on the hallucinated grid, and no mixer reports "no rhythm here."

### 2.2 The grain clock: `beat_interval` vs `calculate_step`

Two derived scalars, easy to confuse (`automixer/utils.py`):

| scalar | formula | what it is | used by |
|---|---|---|---|
| `beat_interval(beats)` | `max(1, round(median(diff(beats)[diff>0])))` `utils.py:16-34` | the **real beat period** (ms). Median of inter-beat gaps → robust to a jittery detector. `0` when `<2` beats. | the grain length base for **every** mixer |
| `calculate_step(beats)` | `max(1, int(mean(beats)/4))` `utils.py:9-13` | a **navigation stride** (~⅛ of track length; musically wrong on purpose — see its own docstring) | `f`/`r` REPL stepping, and `rw`'s chunk-length target |

At load (`:97-102`): `sample_length = beat_interval if beat_interval > 0 else step`. So the **default
grain length is one beat period.**

### 2.3 Scaling the grain against the beat (`l`)

`sample_length` is the grain clock, and `l` rescales it (`amc` path, `:369-380`):

| form | effect | musical reading |
|---|---|---|
| `l /N` | `sample_length /= N` | subdivide the beat — `/2` eighth, `/3` triplet-eighth, `/4` sixteenth |
| `l *N` | `sample_length *= N` | multiply the beat — `*2` half-note, `*8` a 2-bar macro-grain |
| `l <int>` | `sample_length = float(int)` | **absolute milliseconds** — the one way to cut *against* the grid |

The `*`/`/` operands parse as `float` in the `amc` path, so `l *1.5` is legal; the REPL `set_length`
(`:173-185`) takes the same grammar with `int` operands. **Foot-gun:** a bare integer is absolute ms,
not a beat multiple — `l 2` is a 2-millisecond grain, not two beats. Use `l *2` for two beats.

Because `/N` and `*N` are integer/rational scalings of the *same* period, subdivided grains stay
metrically coherent with the pulse: a `T/3` grain still lands on the grid every third grain, so `/3`
reads as a new *reading* of the groove, not a tempo change. To actually move the tempo, use `s`.

---

## 3. The `rw` mixer — random window

`automixer/mixers/default_mixer.py` · the tested default · mode `m rw`.

**Idea:** slide a window across the beat list; from each window pick a *random* beat, cut a grain
there, and append grains until the chunk fills ~⅛-of-track; concatenate all chunks.

### 3.1 Algorithm (`mix`, `:37-49`)

```
chunk_target = calculate_step(beats)                 # ≈ mean(beats)/4
for window in rolling_window(beats, window_divider): # sliding tuples of beat positions
    chunk = _create_chunk(config, window)
    while len(chunk) < chunk_target:
        chunk = chunk.append(_create_chunk(config, window), crossfade=0)
    mix = mix.append(chunk, crossfade=0)             # pure concatenation, one stream
```

### 3.2 The rolling window (`automixer/iterators/rolling_window.py:3-20`)

`window_size = max(1, len(beats) // window_divider)` (clamped ≥1 so a big divider on a short track
never yields an empty mix, `:4-10`). The list is `tee`'d into `window_size` iterators, iterator `i`
advanced by `i`, then `zip`'d — producing sliding tuples of `window_size` **consecutive** beat
positions. So **bigger `w` → smaller window → grains drawn from a tighter time-neighborhood** (more
local, less wandering).

### 3.3 Building one chunk (`_create_chunk`, `:12-34`)

```
chunk = silent(sample_length)
for channel in channels_config:          # each band pulls its OWN random grain
    start = random.choice(window)        # a random beat position in this window
    if snap:                             # off-grid cut, then re-stretch into the slot
        cut_len = max(1, int(sample_length * uniform(0.6, 1.4)))
        g = band_pass(channel, audio[start:start+cut_len])
        if len(g) != sample_length: g = snap_to_length(g, sample_length)
    else:                                # exact-length cut, bit-identical to pre-snap
        g = band_pass(channel, audio[start:start+sample_length])
    chunk = chunk.overlay(g)             # channels are SUMMED on the slot
if sample_speed != 1.0: chunk = change_audioseg_tempo(chunk, sample_speed)
```

Key properties:
- **Content is random, length is fixed.** Each grain starts at a random in-window beat; its length is
  `sample_length` (or, with `snap`, a 0.6–1.4× off-grid span pitch-corrected back to the slot).
- **Channels overlay.** Every band in `c` cuts an *independent* random grain and they are summed onto
  the same slot — split bass/air become two independent grain streams layered together.

`rw` reads `sample_length`, `channels_config`, `window_divider`, `sample_speed`, `snap`, and the beat
list; it ignores euclid/streams/lib/swing/fill. `speed` is added globally afterward.

---

## 4. The `q` mixer — quantized euclidean grid

`automixer/mixers/quantized_mixer.py` · mode `m q`.

Where `rw` inherits whatever groove the source had, `q` **imposes a designed groove**: it subdivides
the beat into `n` slots and fires a grain only on the `k` slots a **euclidean rhythm `E(k, n)`**
marks, cutting each grain from a source **onset** snapped to the grid.

### 4.1 Algorithm (`mix`, `:40-109`)

```
beat_period = beat_interval(beats)                   # fallback sample_length / 500, no floor  :48
pattern     = euclidean(k, n)                        # e.g. E(3,8) = [1,0,0,1,0,0,1,0]          :52
slot_ms     = beat_period / n ;  grain_len = round(slot_ms)                                    :58
slots       = grid_slots(beat_period, pattern, total_ms)   # ms of every HIT                   :61
onsets      = onset_positions(audio, snap_ms=slot_ms)      # source transients, grid-snapped   :62

# HIT loop — the accented euclidean groove
for pos in slots:
    off   = groove offset for this slot (swing sw, or groove_template)                          :83
    grain = _create_grain(config, onsets, grain_len, snap)   # content from an onset            :87
    out   = out.overlay(grain, position = round(pos + off))

# REST loop — gap-fill (fill=True by default)
for slot i NOT in the hit set:
    grain = _create_grain(config, remnants, grain_len, snap) # content from OFF-grid remnants
    out   = out.overlay(grain.apply_gain(fill_gain_db), position = round(i*slot_ms + off))      :96
```

The canvas is `silent(total_ms + slot_ms + grain_len)` so swung-late grains near the end still fit
(`:78-79`).

### 4.2 Euclidean generator — Bjorklund (`automixer/iterators/grid.py:12-48`)

`euclidean(k, n)` spreads `k` hits as evenly as possible over `n` slots via **Bjorklund's algorithm**
(not the `(i*k)%n<k` bresenham shortcut) — chosen deliberately so the result is the *canonical
rotation* musicians expect:

```
E(3,8) = 1 0 0 1 0 0 1 0   tresillo   (hits at 0,3,6)
E(5,8) = 1 0 1 1 0 1 1 0   cinquillo
E(4,4) = 1 1 1 1           four-on-the-floor
```

Edge cases: `n<=0 → []`; `k` clamped to `[0,n]`; `k==0 → all rests`; `k==n → all hits` (`:23-29`).
The Bjorklund core repeatedly pairs "groups" with "remainders" until ≤1 remainder remains, then
flattens (`:31-48`).

`grid_slots(beat_period, pattern, total_ms)` (`:51-66`) tiles the pattern bar-after-bar across the
whole track and emits the output-ms of **only the hit slots**: `[i*slot_ms for i in range(num_slots)
if pattern[i % n]]`.

### 4.3 Grain content: onsets, not random offsets (`_create_grain`, `:123-161`)

Placement is deterministic (the euclidean grid); **content is a random pick among source onsets**:
`candidates = [o for o in onsets if 0 <= o <= len(audio)-grain_len]`, `start = random.choice(candidates)`
(or a random position if there are none). With `snap`, the cut length is the **natural transient unit**
`next_onset - start`, clamped to `[0.5, 1.5] × grain_len`, then pitch-corrected to exactly `grain_len`
via `snap_to_length` (`:145-157`). Per-channel band-pass is overlaid; `sample_speed` stretches last.

### 4.4 Gap-fill for rest slots (`fill` / `nofill` / `fg`)

A bare euclidean pattern leaves `n−k` **silent** rest slots — musically choppy. By default
(`fill=True`), each rest slot is filled with a grain cut from **remnants** and pushed `fill_gain_db`
(default **−6 dB**) below the hits, so the euclidean accents still read as the groove while the gaps
get off-grid texture instead of silence.

**Remnants** (`_remnants`, `:111-121`) are the **midpoints between consecutive snapped onsets** —
the material that landed *between* grid quanta, i.e. exactly the off-grid content the hit grid throws
away. `nofill` restores the pure silent-rest grid; `fg <db>` sets the fill's level relative to hits.

`q` reads euclid `ek/en`, `channels_config`, `sample_speed`, `snap`, `swing`, `groove_template`,
`fill`/`fill_gain_db`, the beat list; `sample_length` only as the period fallback. It ignores
`window_divider`, `streams`, `lib_*`.

---

## 5. The `poly` mixer — phasing polyrhythm

`automixer/mixers/poly_mixer.py` · mode `m poly`.

`rw`/`q` run one grain stream at a time. `poly` runs **N parallel streams at different subdivisions of
the same beat grid and overlays them** — Steve Reich's *Piano Phase*, but granular. Streams at
different ratios coincide periodically and drift out of phase in between.

### 5.1 Algorithm (`mix`, `:35-81`)

```
streams = config.streams or [{"ratio":4}, {"ratio":3}]     # default 3-against-4, full band  :44
ratios  = [max(1, int(s["ratio"])) for s in streams]
cycle   = reduce(lcm, ratios)                              # subdivisions/beat where all realign :54
sub_ms  = beat_period / cycle
onsets  = onset_positions(audio, snap_ms=sub_ms)           # ONE shared pass at the finest grid :57

for s in streams:                                          # render each stream on its own canvas
    step_ms   = beat_period / s.ratio                      # this stream's subdivision period
    grain_len = round(s.get("length") or step_ms)          # @length overrides, else fills the sub
    channels  = s.get("channels") or config.channels_config# per-stream band
    pos = 0
    while pos < total_ms:
        seg = seg.overlay(_create_grain(config, onsets, grain_len, channels), position=round(pos))
        pos += step_ms

out = overlay of all stream segs                                                                :78
```

Two streams at ratios 4 and 3 fire 4 and 3 grains per beat respectively; they coincide every
`LCM(3,4) = 12` subdivisions and phase against each other elsewhere. Because each stream keeps its own
`grain_len` and band-pass, the layers stay audibly distinct.

### 5.2 Stream spec `pr ratio[@length][:low-high]; …`

Parsed at `sample_cut_tool.py:311-326`, `;`-separated:
- `pr 4;3` — two full-band streams, ratios 4 and 3.
- `pr 4@80;3@120` — per-stream grain length in ms (`@length` overrides the subdivision fill).
- `pr 4:1-2000;3:6000-15000` — per-stream band-pass (low band vs high band).

`poly`'s `_create_grain` (`:83-104`) uses the same random-onset-among-candidates content pick as `q`,
band-passes per the stream's channels, and applies `sample_speed`. It has **no snap and no swing**.
`poly` ignores `window_divider`, euclid, `lib_*`, `snap`, `swing`, `fill`.

---

## 6. The `lib` mixer — measured, clustered, sequenced

`automixer/mixers/library_mixer.py` · mode `m lib` · the only mixer with **memory**.

Every other mode picks grains memorylessly. `lib` builds a library of beat-grid grains, **measures**
each, **clusters** them, and **sequences** grain-to-grain motion with a Markov chain over the clusters
— so the output has a directed trajectory (coherent, or deliberately jarring).

### 6.1 Algorithm (`mix`, `:23-81`)

```
grain_len = int(sample_length) or int(beat_period)                                              :35
positions = [b for b in sorted(beats) if 0 <= b <= total_ms-grain_len]                           :39
            (fallback: tile range(0, total_ms-grain_len, grain_len) if <2 positions)
grains    = [audio[p:p+grain_len] for p in positions]        # one grain per fitting beat         :44

feats     = [measure_grain(g) for g in grains]               # 4 axes                             :47
norm      = calibrate(feats)                                 # rank-normalize to [0,1] vs corpus  :48
labels, centroids = cluster(norm, k = lib_clusters)          # k-means (scipy kmeans2)            :51

# Markov walk over clusters
M   = max(1, round(total_ms / grain_len))                    # grains to emit
cur = rng.integers(n_clusters)
for _ in range(M):
    pool = members[cur] or all_grains
    sequence.append(rng.choice(pool))                        # random grain WITHIN the cluster
    cur  = next_cluster(cur, centroids, policy, rng)         # sim → stay near, con → jump far

out = concatenation of grains[sequence]                                                          :67
```

### 6.2 Measurement (`automixer/features.py`)

Each grain is measured on **four axes** (`AXES`, `:11`), via `measure_grain` (`:26-56`):

| axis | librosa feature | meaning |
|---|---|---|
| `centroid` | `spectral_centroid` (mean) | brightness |
| `rms` | `rms` (mean) | loudness |
| `rhythm_density` | `len(onset_detect) / duration` | onsets per second — a single transient → ~0, a busy grain → high |
| `hpss_ratio` | `effects.hpss` energy split | percussive share of total energy, `p/(h+p)` ∈ [0,1] — a pure tone → ~0, noisy/transient material → ~1. Gives `lib con` a real tonal-vs-percussive dimension to jump across, not just a loudness/brightness/density proxy. |

The `hpss_ratio` axis (added 2026-07-21) required **zero changes to `library_mixer.py` itself**:
the mixer calls `calibrate(feats)`, which rank-normalizes whatever `AXES` names (its default),
and `cluster`/`next_cluster` operate on the calibrated rows' shape — the new dimension flows
straight through rank-calibration into clustering. Same measure tract (librosa, already imported)
— no second analyzer.

Grains under 128 samples measure as all-zeros. Audio is peak-normalized to mono float first
(`_to_mono_float`, `:14-23`).

**Calibration is rank/percentile, not absolute** (`calibrate`, `:48-76`): per axis, values are argsort-
ranked (ties average their ranks) and mapped to `[0,1]` **against the grain set itself**. So an axis
that is saturated in raw units (e.g. every grain maximally bright) still spreads across the full range,
and the clustering sees real structure. `n==1 → 0.5`. This is the same self-calibrating discipline the
mesh uses elsewhere: rank against the live corpus so no axis can silently pin.

### 6.3 Clustering (`cluster`, `:79-100`)

**k-means via `scipy.cluster.vq.kmeans2(norm, k, minit="points", missing="warn")`**. `k` is clamped to
`[1, n]`; `k<=1` or `n<=1` collapses to a single cluster. Empty clusters are dropped and **centroids
are recomputed from actual membership** (`:96-99`) so inter-cluster distances used by the policy are
meaningful. If `n_grains < max(4, k)` the run is flagged **degraded** and says so on stdout (`:71-73`)
— it does not fake a full clustering.

### 6.4 Sequencing policy (`next_cluster`, `:103-119`)

A Markov step over clusters weighted by centroid distance `d = ||centroids − centroids[cur]||`:

- **`lib sim` (similarity, default):** `w = 1 / (0.15 + d)` → near clusters (including staying put)
  are likeliest → **hypnotic, coherent** motion.
- **`lib con` (contrast):** `w = d` → far clusters are likeliest, and self-distance 0 means it won't
  stay → **jarring, glitchy** jumps.

Next cluster is `rng.choice(k, p = w/Σw)` (uniform if `Σw<=0`). The two policies produce measurably
different grain-to-grain trajectories over the same library.

`lib` reads `lib_policy`, `lib_clusters`, `sample_length` (grain length), `channels_config`,
`sample_speed`, the beat list. It ignores `window_divider`, euclid, `streams`, `snap`, `swing`, `fill`.

---

## 7. Shared building blocks

### 7.1 Band-pass (`automixer/effects/band_pass.py:5-7`)

```python
def band_pass_filer(low, high, audio):
    return low_pass_filter(high_pass_filter(audio, low), high)
```

`ChannelConfig(low, high)` (`config.py:7-14`) stores the pair and **coerces any 0 cutoff to 1** (pydub
filters dislike 0). Note the field naming reads swapped: the bottom cutoff is passed to
`high_pass_filter` and the top to `low_pass_filter` — correct behavior (high-pass removes below `low`,
low-pass removes above `high`), just counter-intuitively named. Every mixer overlays one band-passed
grain per channel.

### 7.2 Time-stretch (`automixer/effects/change_tempo.py`)

`change_audioseg_tempo(seg, speed)` (`:10-44`) is **pitch-preserving** time-stretch via
`librosa.effects.time_stretch(rate=speed)` (replaced pyrubberband — clean install, comment `:4-7`).
`rate>1` → faster/shorter, `rate<1` → slower/longer. Stereo is stretched per channel then
re-interleaved. On the float→int16 rebuild it scales by `2**15−1` and `np.round(np.clip(...))` to avoid
the `+1.0` wraparound sign-flip click (comment `:33-37`). This one function backs **both** `s` (whole
mix) and `ss` (per grain).

`snap_to_length(seg, target_ms)` (`:47-73`) stretches by `rate = current_ms / target_ms` then trims or
pads to a sample-exact fit; returns the input untouched if already on-length or degenerate. It is what
`snap` uses to force an off-length grain into its slot.

### 7.3 Onset detection (`automixer/iterators/onsets.py:9-32`)

`onset_positions(audio, snap_ms)` runs `librosa.onset.onset_detect` on peak-normalized mono, converts
to ms, and (if `snap_ms>0`) snaps each onset to the nearest grid multiple, de-duplicated and sorted.
On any exception it returns `[]`, and callers fall back to a random position — again, **no floor**.
Shared by `q` (grid-snapped transients) and `poly` (finest-shared-grid transients).

### 7.4 Placement effects (`automixer/effects/groove.py`)

`swing_offset(slot_index, swing_pct, sub_ms)` (`:14-22`): on-beat (even) slot → `0.0`; off-beat (odd)
slot → `max(0,(swing_pct−50)/50) · sub_ms`. So `sw <= 50` (incl. `0`) is a **genuine no-op** (bit-
identical straight placement) and `sw 66 → 0.32·sub_ms`, a 2:1 shuffle. `groove_offsets(...)` applies a
`groove_template` cyclically when present (winning over swing), else per-slot `swing_offset`. Only `q`
consumes these.

### 7.5 Grain shaping — envelope + reverse (`automixer/effects/grain_shape.py`)

Two per-grain primitives (2026-07-21), applied by **every** mixer at the point it already holds a
finished grain — there is no single shared grain loop to hook once, so each mixer calls them in its
own grain function:

- **`apply_envelope(seg, pct)`** — symmetric `fade_in`/`fade_out` taper, `pct`% of the grain's own
  length per edge, clamped to at most half the grain. `pct <= 0` is a true no-op. Driven by
  `env` (default **8.0** — always on: a hard-cut grain boundary is an audible click, not a
  creative choice; `amc env 0` restores the hard-cut path, which is how the bit-identity fixtures
  pin the pre-envelope byte streams).
- **`maybe_reverse(seg, prob, rng)`** — reverses the grain with probability `prob` (`rv`, default
  **0.0**). `prob <= 0` short-circuits **without touching the RNG at all**, so an `rv 0` render
  draws exactly as many random numbers as before the feature existed — the seed-reproducibility
  contract holds unchanged for every pre-existing config.

Where each mixer applies them:

| mixer | reverse drawn | envelope applied |
|---|---|---|
| `rw` — `default_mixer._create_chunk` | per **channel**, right after each channel's slice (each channel already cuts from its own random `start_cut`, so an independent per-channel draw is consistent with the mixer's existing character — deliberately *not* "fixed" to match the others) | once, on the finished chunk, after `ss` |
| `q` — `quantized_mixer._create_grain` | **once per grain**, on the primary slice before the channel loop; the single decision is re-applied to each channel's own slice | once, on the finished grain, after snap + `ss` |
| `poly` — `poly_mixer._create_grain` | once per grain, same pattern as `q` | once, after `ss` |
| `lib` — `library_mixer._render_grain` | once per grain, via a **fresh unseeded** `random.Random()` — grain *selection* is fully seed-determined before `_render_grain` runs, but the reverse coin itself is **not seed-reproducible** (honest, documented gap; see §9) | once, after `ss` |

In the multi-band mixers reverse is a property of the **grain as a whole**: one coin per grain,
every band shares the outcome. (A per-channel redraw could reverse the low band while the highs
play forward — an incoherent scrambled grain; that was a real fix-round bug, now pinned by
`test_reverse_decision_drawn_once_per_grain_not_per_channel` in each mixer's test file.)

### 7.6 Dual-source grinding (`slice_source`, `automixer/utils.py:171-206`)

`amc src2 <path>` decodes a second source into `config.audio2` (cached by path, re-decoded only
when the path changes), and any `c` band prefixed `2:` sets `ChannelConfig(source2=True)`. Every
mixer's per-channel cut routes through `slice_source(config, channel, start_ms, length_ms)`, which
picks the source per band:

- **Primary path** — untagged bands, and `source2=True` bands when no `audio2` is loaded: the
  legacy plain slice `audio[start:start+length]`, which **truncates at the source's tail and never
  wraps** (wrapping the track's opening onto its own tail would be an audible regression of the
  ordinary single-source path — review-scoped deliberately).
- **Source-2 path** — `start % len(audio2)`, then a **modulo-wrap** slice: every call returns
  exactly `length_ms` of real audio even when source 2 is shorter (or longer) than the primary.
  Beat detection, grain positions, and windows always come from the **primary** source; source 2
  only supplies raw material.

The only mixer that required restructuring was **`lib`**: `_render_grain` used to receive an
already-cut grain and had no position to re-slice from, so it is now **position-aware**
(`_render_grain(config, grain, position_ms)`), letting each channel re-cut the same grid position
from whichever source it names. `poly`'s per-stream `:low-high` bands (from `pr`) construct their
own channels and are always primary-source — the `2:` tag lives only in the `c` grammar.

**Uxn control mode (`--uxn-ctrl`): dual-source does not apply.** The ROM owns the full `c` band
string every tick (none of `paramgen.rom`'s band strings carries a `2:` prefix), and
`config_automix` rebuilds `channels_config` from scratch on every `c` token — so no band can ever
read `audio2` under ROM control. The TUI does not even load Source B in Uxn mode and logs, once:
"Uxn mode: ROM owns the bands — per-track A/B tags and Source B don't apply (env/rv do)". `env`
and `rv` **do** apply there (seeded once per run; ROM lines never emit `env`/`rv` tokens, so every
tick's `config_automix` falls back to the seeded values). See `../uxn_ctrl/README.md`.

---

## 8. Loudness & export

Raw automixes are routinely near-inaudible, so **every** export is loudness-normalized first
(`normalize_loudness`, `cutter/sample_cut_tool.py:24-38`, applied at `:430` before both wav and mp3):

```
gain = target_dbfs - seg.dBFS                    # bring RMS to target
gain = min(gain, peak_dbfs - seg.max_dBFS)       # but never exceed the true-peak ceiling
```

Targets are env-tunable: `GRAINNEUKELN_TARGET_DBFS` (RMS, default **−16.0**) and
`GRAINNEUKELN_PEAK_DBFS` (peak ceiling, default **−1.0**). Because the boost is capped by peak
headroom, the mp3 encode never clips; a mix already over the ceiling is *attenuated*. Silent / `-inf
dBFS` segments pass through untouched.

Output filename: `<source>___mix_cut<int(sample_length)>-vtgsmlpr____<YYYY_MM_DD_HHMM>.mp3` (`:436-441`),
`.wav` too when wav export is enabled (`set_wav_enabled`). With self-feed on (`aminf`, `:164-167`),
the freshly written mp3 is reloaded as the source so the next automix grinds its own output —
recursive granular resynthesis. (Note: self-feed length-amplifies; feed short.)

---

## 9. Determinism & reproducibility

- **Placement is deterministic, content is random** — per mode. `q`'s euclidean grid and `poly`'s
  subdivision steps are fixed by the params; *which onset/grain* fills each slot is a random pick. So
  two runs with identical params share a groove but differ in texture. This is the design (README:
  "two runs give two different tracks").
- **No mode is reproducible run-to-run without seeding.** Unseeded (the default), `rw`/`q`/`poly`
  use the global `random` module and `lib` an unseeded `np.random.default_rng()`. `amc seed <N>`
  (or the `--seed N` CLI flag) seeds every mixer's RNG (`apply_seed`, `automixer/utils.py`) —
  same seed + same params → byte-identical output. One documented exception: `lib` mode's
  per-grain **reverse** coin (`rv`) uses a fresh unseeded `random.Random()` even under `seed`
  (§7.5) — grain selection stays seed-stable, the reverse decisions do not.
- **No beat floor anywhere.** Every mixer grinds on the detected grid, real or hallucinated, and none
  can report "this source has no rhythm." Check the printed beat count if an output comes back empty or
  dead — 0 detected beats is the only true "nothing to build on" case.

---

*Line references are against the repository at the time of writing; if the code has moved, grep the
quoted function names — they are stable.*
