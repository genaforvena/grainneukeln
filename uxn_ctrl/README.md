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

- **`paramgen.tal`** (uxntal) / **`paramgen.rom`** (619 bytes, prebuilt & committed, like the
  mesh's own `lease-gate.rom`/`band-gate.rom` pilots) — a deterministic sequencer. Given two argv
  tokens (a tick and a macro-tick, decimal ASCII, `uxncli` feeds each newline-terminated in
  turn), it prints one line: `l <ms> w <n> s <ratio> c <lo>,<hi>;... ss <ratio>`. Selection is
  **table-lookup only**, one 2-bit field per parameter — `tick_lo & 3` picks among 4 `l` values,
  `(tick_lo >> 2) & 3` among 4 `w` values, `(tick_lo >> 4) & 3` among 4 `s` values,
  `(tick_lo >> 6) & 3` among 4 `c` band-pairs — spending all 8 bits of the first token (a
  256-tick period). `ss` reads the second token's low 2 bits (`macro_tick_lo & 3`) among 4 `ss`
  values, since the first token had no bits left — a 1024-tick period overall before the full
  5-param sequence repeats. The ROM never formats or computes the values themselves; those are
  fixed ASCII strings baked into the ROM, the same pool-quantization `grainneukeln`'s own recipe
  conventions already use. No floats anywhere — `s`'s ratios (`0.5`/`0.8`/`1.3`/`2.0`), `ss`'s
  ratios (`0.5`/`0.75`/`1.25`/`2.0`, the same distance-from-1.0 pool `mesh-sound-reflex` quantizes
  to) and `c`'s band pairs are baked-in text, parsed as a float/ints only on the Python side,
  exactly like `l`/`w` always were.
- **`build.sh`** — compiles the vendored `uxnasm`/`uxncli` (MIT, Devine Lu Linvega et al.,
  copyright headers preserved per-file) for the current platform and reassembles the ROM.
  `bin/` is gitignored; every machine (dev box, CI runner) builds its own ~26KB emulator, the
  ROM itself is portable and byte-identical everywhere.
- **`src/`** — vendored Uxn core (`uxn.c`/`uxn.h`, `uxnasm.c`, `uxncli.c`, `devices/`).

## Host side (`automixer/uxn_stream.py`)

```python
from automixer.uxn_stream import uxn_tick, run_uxn_sequence

uxn_tick(0)                       # -> "l 200 w 4"  (deterministic per tick)
run_uxn_sequence(cutter, 8)       # drives 8 renders of `cutter` from ticks 0..7
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
```

Any ROM works as long as it prints `l <ms> w <n>` (or any other `amc`-grammar tokens) to
stdout per tick — `--uxn-ctrl` doesn't hardcode `paramgen.rom`'s specific sequencing logic,
only its wire format.

## Scope / what's NOT done

- `l`, `w`, `s`, `c`, `ss` are all sequenced now. `l`/`w`/`s`/`c` spend the whole 8-bit tick_lo
  byte of the first argv token (4x4x4x4 = 256-tick period); `ss` had no bits left there, so it
  reads a **second argv token** — a coarser "macro tick" (`tick // 256`, host-computed in
  `uxn_stream.uxn_tick`) whose low 2 bits pick its pool entry. Net period before the whole
  5-param sequence repeats: 256 x 4 = 1024 ticks.
- No real-time/live control (Option B territory) — `grainneukeln` has no live audio thread to
  target. If that changes, Option A's IPC shape (stdout stream -> parser) ports over close to
  as-is; only the "one process per tick" plumbing would need to become "one persistent process,
  one line read per audio callback."
