# grainneukeln — `amc` Parameter Reference

The complete reference for the automix command line. For *how* each parameter drives the algorithm,
see [`ALGORITHMS.md`](ALGORITHMS.md).

```bash
python main.py <source> <output_dir> amc <param value> <param value> …
```

Parameters are read positionally by key: the parser finds each key token and takes the **next** token
as its value (`config_automix`, `cutter/sample_cut_tool.py:363-533`). A fresh config is built on every
`amc` call — unset params fall back to the defaults below.

---

## Global parameters (all modes)

| param | value | default | effect |
|---|---|---|---|
| `m` | `rw` \| `q` \| `poly` \| `lib` | `rw` | mixer mode (see per-mode sections) |
| `s` | float | `1.0` | **whole-mix** speed, applied once to the finished mix (pitch-preserving). `<1` slower, `>1` faster. Post-process, not part of grain selection. |
| `ss` | float | `1.0` | **per-grain** speed, applied to each grain as it's cut (pitch-preserving). Warps micro-texture. |
| `l` | `/N`, `*N`, or `<int>` | 1 beat | grain length. `/N` = beat ÷ N (subdivide), `*N` = beat × N (multiply), bare int = **absolute ms**. See the foot-gun note below. |
| `c` | `[2:]low,high;[2:]low,high;…` (Hz) | `0,15000` | band-pass channels. Each `low,high` band pulls its **own** grain; bands are layered. `;`-separated. A `0` cutoff is coerced to `1`. A band prefixed `2:` pulls its grains from the `src2` source (see the `2:` prefix note below). |
| `env` | float % | `8.0` | attack/release taper on **every** grain: `pct`% of the grain's own length faded on each edge, clamped to at most half the grain. Always on by default (a hard-cut grain boundary is an audible click); `env 0` disables. Applies in all 4 modes. |
| `rv` | float `0..1` | `0.0` | per-grain reverse probability. Decided **once per grain** in `q`/`poly`/`lib` (all bands share the outcome); `rw` draws per channel (each of its channels already cuts from its own random position). `rv 0` draws no random numbers at all, preserving seeded byte-identity for existing configs. In `lib` mode the reverse coin is **not** seed-reproducible (documented gap — see `ALGORITHMS.md` §7.5). Applies in all 4 modes. |
| `src2` | file path | unset | **dual-source grinding**: load a second source (decoded once, cached by path). Only `c` bands tagged `2:` read it; the beat grid always comes from the primary source. |

### The `c` `2:` prefix — dual-source bands

With `src2 <path>` loaded, any `c` band written `2:low,high` cuts its grains from the **second**
source instead of the primary — e.g. `amc src2 drums.mp3 c 0,250;2:250,15000` layers the primary's
bass under the second file's top end, on the primary's beat grid. Semantics (`slice_source`,
`automixer/utils.py`):

- Grain positions are always drawn from the **primary** source's beat grid/windows; a `2:` band
  re-reads the same position in source 2 **modulo source 2's length** — a second source shorter
  (or longer) than the primary wraps instead of truncating, so every source-2 grain comes back
  full-length.
- Untagged bands keep the legacy plain slice, which truncates at the primary's tail and never
  wraps. A `2:` band with no `src2` loaded falls back to that same primary path.
- In `poly` mode, per-stream `:low-high` bands (from `pr`) build their own channels and are always
  primary-source; the `2:` tag lives only in the `c` grammar (read when a stream has no band of
  its own).
- **Uxn control mode (`--uxn-ctrl`): `src2`/`2:` do not apply.** The ROM owns the full `c` band
  string every tick and never emits a `2:` prefix, so no band can read source 2 under ROM control
  (`env`/`rv` do apply there — see `../uxn_ctrl/README.md`).

### The `l` foot-gun

`l /N` and `l *N` are beat-relative (`/2` eighth, `*4` four beats). A **bare integer is absolute
milliseconds**, *not* a beat count: `l 2` is a 2 ms grain. For "two beats" write `l *2`. The `*`/`/`
operands accept floats in the `amc` path (`l *1.5` is legal).

---

## Placement effects (composable — `rw` and `q`)

| param | value | default | effect | modes |
|---|---|---|---|---|
| `snap` | flag | off | pitch-preservingly stretch each grain to land exactly in its slot instead of smearing | `rw`, `q` |
| `w` | int | `2` | window divider — windows = `total_beats / w`. Bigger `w` → smaller, more local windows | `rw` only |
| `sw` | float % | `0` | swing: delay every off-beat grain. `≤50` = straight (no-op), `66` = 2:1 shuffle | `q` only |

---

## Mode `q` — quantized euclidean grid

| param | value | default | effect |
|---|---|---|---|
| `ek` | int | `3` | euclidean hit count `k` in `E(k,n)` |
| `en` | int | `8` | euclidean slot count `n` — the beat is divided into `n` slots |
| `snap` | flag | off | cut the natural transient unit and stretch it into the slot |
| `sw` | float % | `0` | swing (see above) |
| `nofill` | flag | fill on | disable rest-slot gap-fill → pure silent-rest euclidean grid |
| `fg` | float dB | `-6.0` | gap-fill gain relative to the hits (only when fill is on) |

`E(k,n)` places `k` hits as evenly as possible over `n` slots (Bjorklund). `E(3,8)` tresillo, `E(5,8)`
cinquillo, `E(4,4)` four-on-the-floor. Grain content is a source **onset** snapped to the grid; the
`n−k` rest slots are filled (by default) with off-grid remnant material `fg` dB below the hits.

```bash
python main.py song.mp3 out/ amc m q ek 3 en 8                 # tresillo, gaps filled
python main.py song.mp3 out/ amc m q ek 5 en 8 snap sw 66      # cinquillo, snapped, shuffled
python main.py song.mp3 out/ amc m q ek 5 en 13 nofill         # sparse, silent rests
python main.py song.mp3 out/ amc m q ek 2 en 5 fg -12          # quiet fill under sparse hits
```

---

## Mode `poly` — phasing polyrhythm

| param | value | default | effect |
|---|---|---|---|
| `pr` | `ratio[@length][:low-high];…` | `4;3` | one stream per `;` segment. `ratio` grains/beat; optional `@length` grain ms; optional `:low-high` band. |

N streams at different subdivisions overlay and phase against each other. `4;3` is 3-against-4,
coinciding every `LCM(3,4)=12` subdivisions.

```bash
python main.py song.mp3 out/ amc m poly pr 4;3                        # 3-against-4, full band
python main.py song.mp3 out/ amc m poly pr 4:1-2000;3:6000-15000      # low band vs high band
python main.py song.mp3 out/ amc m poly pr 5;4;3 ss 0.8               # 3-way phase, grains slowed
python main.py song.mp3 out/ amc m poly pr 4@80;3@120                 # staccato, per-stream length
```

---

## Mode `lib` — measured, clustered, sequenced

| param | value | default | effect |
|---|---|---|---|
| `lib` | `sim` \| `con` | `similarity` | Markov policy: `sim` stays near the current cluster (coherent), `con` jumps far (glitchy). `con` matches any value starting `con`. |
| `lk` | int | `6` | k-means cluster count |

Grains are measured on brightness / loudness / rhythm-density / harmonic-vs-percussive ratio
(librosa HPSS), rank-calibrated against the grain set,
k-means clustered, then sequenced by a distance-weighted Markov walk. Fewer than `max(4, lk)` grains →
honest degraded run (reported on stdout).

```bash
python main.py song.mp3 out/ amc m lib sim lk 6      # hypnotic, in-cluster
python main.py song.mp3 out/ amc m lib con lk 8      # glitchy, jumps between clusters
```

---

## Cross-mode parameter matrix

Which mode actually reads which parameter (`✓` used, `—` ignored). `speed s` is applied globally in
the runner for all modes; a grain's `sample_speed ss` and band-pass `c` are honored by all four.

| param | `rw` | `q` | `poly` | `lib` |
|---|:--:|:--:|:--:|:--:|
| `s` (whole-mix speed) | ✓ global | ✓ global | ✓ global | ✓ global |
| `ss` (per-grain speed) | ✓ | ✓ | ✓ | ✓ |
| `c` (channels/bands) | ✓ overlaid | ✓ overlaid | ✓ default band | ✓ overlaid |
| `l` (grain length) | ✓ slot len | fallback only | fallback only | ✓ grain len |
| `w` (window divider) | ✓ | — | — | — |
| `ek` / `en` (euclid) | — | ✓ | — | — |
| `pr` (poly streams) | — | — | ✓ | — |
| `lib` / `lk` | — | — | — | ✓ |
| `snap` | ✓ | ✓ | — | — |
| `sw` (swing) | — | ✓ | — | — |
| `nofill` / `fg` (gap-fill) | — | ✓ | — | — |
| `env` (grain envelope) | ✓ | ✓ | ✓ | ✓ |
| `rv` (grain reverse) | ✓ per channel | ✓ per grain | ✓ per grain | ✓ per grain |
| `src2` / `2:` bands | ✓ | ✓ | ✓ (via `c` only) | ✓ |

Passing a parameter to a mode that ignores it is harmless — it's simply not read.

---

## Environment variables

| var | default | effect |
|---|---|---|
| `GRAINNEUKELN_TARGET_DBFS` | `-16.0` | RMS loudness target on export |
| `GRAINNEUKELN_PEAK_DBFS` | `-1.0` | true-peak ceiling (caps the normalization boost so the encode never clips) |

---

## Recipe patterns

These are the shapes used by the mesh's batch grinders; they compose the primitives above.

**Subdivide the groove without moving the tempo** — re-read the same pulse at different grain scales:

```bash
amc l /8      # 48ms micro-grains (at a 384ms beat)
amc l /2      # eighth-note grains
amc l *4      # half-bar macro-grains
amc l *16     # 2-bar macro-windows
```

Spread `l` widely in **both** directions (sub-beat `/8../2` and multi-beat `*2..*32`), not clustered
near `1×`, to get the full range from stuttering micro-texture to long stretched macro-grains. Keep the
largest grains well under the source clip length (a `*32` grain at a 384 ms beat is ~12 s — feed it a
clip much longer than that).

**Bias toward a slowed final character** — grind, then time-stretch the finished mix down:

```bash
amc m q ek 3 en 8 s 0.8 ss 0.85 l *8      # slow grid + slow grains + macro-window
```

Or slow the whole mix as a finishing pass with `ffmpeg` (`atempo` for pitch-preserving, `asetrate` for
a tape-style pitch-drop) — that keeps the grind varied while the delivered character is consistently
slow.

**Keep it fast** — the automixer is ~O(n²) in clip length (band-pass + segment-append is pure Python).
Feed **short clips** (a few seconds to under a minute); long feeds grind slowly and can silently fail
above ~65 s. Short clips also fit live/ambient-capture use.
