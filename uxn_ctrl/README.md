# uxn_ctrl — Uxn external control layer (Option A, issue #13)

Implements **Option A** from [#13](https://github.com/genaforvena/grainneukeln/issues/13):
Uxn runs as a separate process and hands `grainneukeln` a stream of parameter changes through
its *existing* `amc` grammar. The audio engine is untouched — every line this module produces
is exactly what a human types at the REPL.

## Why Option A, not Option B

The issue's own "Potential Challenges" table names the real fault line: Uxn is an 8-bit VM
with no floats and a 64KB address space. That's a *good* fit for the **sequencing decision**
— "which pool entry does tick N select" is pure small-integer arithmetic — and a *bad* fit for
`grainneukeln`'s actual DSP: the ~O(n²) numpy mixer and librosa beat detection need floating
point and unbounded working memory a Uxn ROM structurally cannot provide. Option B (embedding
the VM inside the audio thread) would still have to solve that same mismatch just to move
grains around, for no benefit Option A doesn't already get more simply. So: keep Uxn to the
part it's actually good at, keep the DSP in Python/numpy where it already works.

## What's here

- **`paramgen.tal`** (uxntal) / **`paramgen.rom`** (767 bytes, prebuilt & committed, like the
  mesh's own `lease-gate.rom`/`band-gate.rom` pilots) — a deterministic sequencer. Given
  **four** argv tokens, decimal ASCII, `uxncli` feeds each newline-terminated in turn, **in this
  order**: a `feedback` byte, a `tick`, a macro-tick, and a mode-tick. Feedback MUST arrive first —
  the ROM emits `c`'s string while processing the SECOND line it reads (the tick), so a feedback
  value read any later could never influence that selection. It prints one line: `l <ms> w <n> s
  <ratio> c <lo>,<hi>;... ss <ratio> m <mode>`. Selection is **table-lookup only**, one 2-bit
  field per parameter — `tick_lo & 3` picks among 4 `l` values, `(tick_lo >> 2) & 3` among 4 `w`
  values, `(tick_lo >> 4) & 3` among 4 `s` values, `(tick_lo >> 6) & 3` (EOR'd with
  `feedback_lo & 3` -- see "Closed-loop feedback" below) among 4 `c` band-pairs — spending all 8
  bits of the tick token (a 256-tick period). `ss` reads the macro-tick token's low 2 bits
  (`macro_tick_lo & 3`) among 4 `ss` values, since the tick token had no bits left. `m` reads a
  **fourth** token (see "Mode sequencing" below). The ROM never formats or computes the values
  themselves; those are fixed ASCII strings baked into the ROM, the same pool-quantization
  `grainneukeln`'s own recipe conventions already use. No floats anywhere — `s`'s ratios
  (`0.5`/`0.8`/`1.3`/`2.0`), `ss`'s ratios (`0.5`/`0.75`/`1.25`/`2.0`, the same distance-from-1.0
  pool `mesh-sound-reflex` quantizes to), `c`'s band pairs, and `m`'s mode words are baked-in text,
  parsed as a float/int/word only on the Python side, exactly like `l`/`w` always were.

### Mode sequencing (2026-07-24, issue #13 extension)

The sequencer's biggest unused axis was WHICH algorithm cuts the grains (`rw`/`q`/`poly`/`lib`) —
it only ever varied params *within one fixed mode*. The mode is now a 6th pooled param: a fourth
argv token (the "mode-tick", host-computed as `tick // 4` in `uxn_stream._MODE_PERIOD`) drives it
via `mode_tick_lo & 3`, picking among `rw`/`q`/`poly`/`lib` (`config.AutoMixerConfig.modes`). So a
single ROM-driven run **moves through cutting algorithms** — random-window → quantized beat-grid →
polyrhythmic streams → library/cluster — not just through their knobs. The 4-tick period keeps each
mode in place long enough to read: a per-tick mode flip would be chaos, not music. All four modes
degrade safely with no extra config (`poly` defaults to a 4:3 stream pair, `lib` to 6 similarity
clusters), and `pr`/`lk` can be pre-seeded the same way `env`/`rv` are if you want to shape them.

### Closed-loop feedback (2026-07-21; adaptive ceiling + per-tick regional 2026-07-24)

`idx_c = ((tick_lo >> 6) & 3) EOR (feedback_lo & 3)` — a host-measured byte perturbs WHICH `c`
band-pair a tick selects. `feedback=0` is a true no-op (`x EOR 0 == x`), so the open-loop
behaviour above is exactly what you get when the host doesn't compute a real feedback value.
`automixer.uxn_stream.run_uxn_sequence(..., closed_loop=True)` (CLI: `--uxn-feedback`) computes a
real feedback byte each tick via `_measure_feedback_byte`, built from the one existing measure
tract (`automixer.features.measure_grain` — no new analyzer) over 2000ms beat-grid grains. Only
the byte's low 2 bits reach `idx_c`, so it is a coarse perturbation key, not a precision control
signal — and it is pure deterministic arithmetic over already-loaded audio (no RNG touched, the
seed-reproducibility contract is unaffected).

Two fixes landed 2026-07-24 over the original whole-source-average:

- **Adaptive ceiling.** The original divided by a fixed 5.0 onsets/sec; uniformly busy material
  saturated to byte 255 and pinned `idx_c` at a constant XOR-by-3 (measured 2026-07-21: 5/8
  sampled offsets of a busy passage → 255). The byte now scales against the source's OWN peak
  density times headroom (`_FEEDBACK_HEADROOM = 1.25`), which structurally keeps even the busiest
  region below 255 — so different busy-ness levels map to different perturbations instead of
  collapsing to one. (The earlier 300ms measure window saturated on *everything* — a single onset
  in 300ms extrapolates past 3/sec — fixed by the 2000ms window.)
- **Per-tick regional measurement.** The original averaged the WHOLE source every tick — the same
  byte every call, i.e. a constant per-run `idx_c` offset, not a closed loop. The byte now reads
  the region at `positions[tick % len(positions)]` each tick (profile built once and cached on the
  cutter, capped at 24 grains), so a varied song yields different bytes — and thus a moving
  `idx_c` — across the run. A genuinely uniform source still yields a near-constant byte, which is
  honest: nothing varies for the loop to react to.
- **`build.sh`** — compiles the vendored `uxnasm`/`uxncli` (MIT, Devine Lu Linvega et al.,
  copyright headers preserved per-file) for the current platform and reassembles the ROM.
  `bin/` is gitignored; every machine (dev box, CI runner) builds its own ~26KB emulator, the
  ROM itself is portable and byte-identical everywhere.
- **`src/`** — vendored Uxn core (`uxn.c`/`uxn.h`, `uxnasm.c`, `uxncli.c`, `devices/`).

## Host side (`automixer/uxn_stream.py`)

```python
from automixer.uxn_stream import uxn_tick, run_uxn_sequence

uxn_tick(0)                    # -> "l 200 w 4 s 0.5 c 0,0;1000,15000 ss 0.5 m rw"  (open-loop)
uxn_tick(0, feedback=3)        # -> "l 200 w 4 s 0.5 c 0,1000;4000,18000 ss 0.5 m rw"  (c perturbed)
uxn_tick(4)                    # -> "... ss 0.5 m q"   (mode-tick 4//4=1 -> quantized mode)
uxn_tick(8)                    # -> "... ss 0.5 m poly"  (mode-tick 8//4=2 -> polyphonic mode)
run_uxn_sequence(cutter, 8)                    # 8 renders, ticks 0..7, open-loop (modes rw then q)
run_uxn_sequence(cutter, 16, closed_loop=True) # each tick's feedback measured from the current region
```

`uxn_tick` spawns `uxncli` once per tick (same one-shot-per-call shape as the mesh's own
`mesh-lease-gate`/`mesh-band-gate`) — simple, testable, and there is no live audio thread in
`grainneukeln` (an offline batch renderer) for a persistent socket/IPC loop to feed in real
time, so a subprocess-per-tick stream is the actual right shape here, not a simplification of
a "real" real-time design.

## CLI

```sh
python main.py song.mp3 out/ --uxn-ctrl --uxn-ticks 8
python main.py song.mp3 out/ --uxn-ctrl my_pattern.rom --uxn-ticks 16   # your own ROM
python main.py song.mp3 out/ --uxn-ctrl --uxn-ticks 8 --uxn-feedback   # closed-loop
```

Any ROM works as long as it prints `l <ms> w <n>` (or any other `amc`-grammar tokens) to
stdout per tick — `--uxn-ctrl` doesn't hardcode `paramgen.rom`'s specific sequencing logic,
only its wire format.

## Composing with the rest of the `amc` grammar (env/rv: yes · src2/Source B: no)

Each tick's ROM line carries `l w s c ss m` tokens, and `config_automix` only overrides fields
whose tokens are present — everything else falls back to the cutter's cached config. Two opposite
consequences:

- **Params the ROM never emits compose.** Seed them once before the run and they hold for every
  tick: the TUI's Uxn path does exactly this for the grain-shaping params (`env`/`rv`) via a
  single `config_automix("amc env <v> rv <v>")` call before the tick loop, and every subsequent
  ROM tick falls back to those cached values.
- **Anything the ROM DOES emit is ROM-owned — dual-source grinding does not apply.** The full `c`
  band string is rewritten from scratch on every tick, and none of `paramgen.rom`'s band strings
  carries a `2:` prefix, so no band can ever be tagged `source2` under ROM control: `src2`, `2:`
  band tags, and the TUI's per-track A/B toggle are all inert in Uxn mode (structural guard:
  `tui/test_app.py::UxnBandHonestyGuardTest`). The TUI does not load Source B in Uxn mode and
  says so loudly, once per run: "Uxn mode: ROM owns the bands — per-track A/B tags and Source B
  don't apply (env/rv do)". Do not document or script these as composable — they structurally
  cannot be, short of building your own ROM that emits `2:`-prefixed bands.

## Scope / what's done

- `l`, `w`, `s`, `c`, `ss`, `m` are all sequenced now. `l`/`w`/`s`/`c` spend the whole 8-bit
  tick_lo byte of the tick argv token (4x4x4x4 = 256-tick period); `ss` had no bits left there,
  so it reads a **third argv token** — a coarser "macro tick" (`tick // 256`, host-computed in
  `uxn_stream.uxn_tick`) whose low 2 bits pick its pool entry. `m` reads a **fourth argv token** —
  a "mode tick" (`tick // _MODE_PERIOD`, default 4) whose low 2 bits pick the cutting algorithm.
- Closed-loop feedback is done — a per-tick regional byte, scaled by the source's own adaptive
  ceiling, perturbs `idx_c` each tick; `feedback=0` keeps the open-loop behaviour (a true no-op
  for idx_c; the appended `m` axis is orthogonal and present in both modes).
- TUI exposure is done (Run panel: enable checkbox, ROM path, ticks, closed-loop checkbox — same
  `run_uxn_sequence` worker). Rough edge from the live smoke test (2026-07-21): per-tick renders
  surface via the run log (`[uxn tick N] …`) and the Outputs panel's directory scan — there is no
  single "last artifact" completion line per tick the way single/series runs report one.
- No real-time/live control (Option B territory) — `grainneukeln` has no live audio thread to
  target. If that changes, Option A's IPC shape (stdout stream -> parser) ports over close to
  as-is; only the "one process per tick" plumbing would need to become "one persistent process,
  one line read per audio callback."
