# Grain effects & control expansion — design

**Date:** 2026-07-21
**Status:** approved (operator, in-conversation)
**Branch:** direct to `master` (small, independent, additive features; matches how the
uxn Option A work landed)

## Context & problem

`grainneukeln` grinds a source into new audio via beat-grid grains, four mixer modes (`rw`/`q`/
`poly`/`lib`), and an external Uxn control layer (issue #13) that sequences `amc` params
open-loop. Five gaps were identified (README "what's it is" ideation, 2026-07-21) and approved
by the operator for implementation, with TUI parity and doc updates required for each:

1. **Grain envelope** — grains are hard-cut today (only `snap` time-stretches to fit a slot);
   no attack/release fade exists anywhere, so grain boundaries click.
2. **Reverse grains** — no per-grain reverse playback exists; a classic granular-synthesis
   primitive missing entirely.
3. **HPSS clustering axis** — `lib` mode clusters grains on 3 axes (centroid/RMS/rhythm-density,
   `automixer/features.py`); no harmonic/percussive axis exists, though `lib con` (contrast) is
   exactly the mode that would benefit from jumping between percussive and harmonic material.
4. **Dual-source grinding** — every mixer grinds one `config.audio`; the existing multitrack
   band concept (independent low/high-Hz streams via `ChannelConfig`) has no notion of a *second
   source file* for a band to pull from.
5. **Closed-loop Uxn control** — `uxn_ctrl/paramgen.rom` picks params by tick alone
   (`automixer/uxn_stream.py`); it never reacts to the actual source's measured character.

## Goals

- Land all 5 as small, composable, independently-testable additions to the existing `amc`
  grammar / mixer architecture — no new mixer modes, no rewrite of any existing mixer.
- Every new capability reachable from **CLI, REPL, and TUI** — TUI parity is a hard requirement,
  including for Uxn control, which currently has **zero** TUI exposure (a pre-existing gap, not
  just a gap in the new work).
- Preserve existing invariants: the `seed`-reproducibility contract (byte-identical output for
  the same seed+params), the "no beat floor" rhythm-seeking behavior, and — for Uxn — exact
  byte-for-byte output of today's `paramgen.rom` when the new feedback input is absent/zero.
- Update `README.md`, `docs/PARAMETERS.md`, `docs/ALGORITHMS.md`, and `uxn_ctrl/README.md` to
  document every new param/flag.

## Non-goals (YAGNI)

- No real-time/streaming grinding (still an offline batch renderer — out of scope, unrelated to
  these 5 features).
- No N-source grinding (`src2` only — a genuine 3rd source is not requested and adds grammar
  complexity for no asked-for benefit).
- No Uxn ROM redesign beyond the minimal 3rd-argv-token extension — the existing table-lookup
  architecture is sound and explicitly preferred (see `uxn_ctrl/README.md`'s "why Option A" note).
- No new librosa analyzer for HPSS — `librosa.effects.hpss` is called from the **existing**
  `features.py` measure tract (mesh/tool doctrine: one measure tract, never a second analyzer).

## Design

### 1. Grain envelope

New `amc env <pct>` (0–100, default baked into `AutoMixerConfig.env_pct`, e.g. `8`) sets the
attack/release taper as a percentage of each grain's final length. Applied via pydub's
`AudioSegment.fade_in(ms).fade_out(ms)` — no new DSP dependency. **Always on** (`env 0` is the
explicit opt-out); this is a defect fix, not a creative toggle, so unlike `snap` it defaults on.

Applied **last**, immediately before each grain is overlaid/placed, in all 4 mixers (after
band-pass, reverse, and any tempo change) — it shapes the boundaries of what actually gets
stitched together.

### 2. Reverse grains

New `amc rv <0..1>` sets the probability each individual grain is reversed
(`AudioSegment.reverse()`, confirmed present in pydub). Default `0` (off, matches today's
character exactly). Decision drawn from whichever RNG each mixer already threads through
`apply_seed`/`np.random.default_rng` — **not** a fresh unseeded `random.random()` call — so the
`seed`-reproducibility contract holds. Applied right after the raw slice is cut, before
band-pass (order doesn't audibly matter here, but cutting-then-reversing keeps the slice-position
math untouched).

### 3. HPSS clustering axis

`features.AXES` gains a 4th entry, `"hpss_ratio"` — percussive energy / (harmonic + percussive
energy), via `librosa.effects.hpss(y)` inside the existing `measure_grain`. Always computed for
`m lib` (consistent with the other 3 axes being unconditional); folds into the existing
rank-calibration (`calibrate`) and `kmeans2` clustering with no other changes to `library_mixer.py`
beyond passing the new axis through.

### 4. Dual-source grinding

- New `amc src2 <path>` loads a second file into the cutter, mirroring the existing
  `SampleCutter._load_audio` decode-by-extension logic, cached by path (`self.audio2`,
  `self._audio2_path`) so repeated `amc` calls don't re-decode. Passed to `AutoMixerConfig` as
  `audio2`.
- `ChannelConfig` gains `source2: bool = False`. The `c` band grammar accepts an optional `2:`
  prefix per semicolon-separated band: `c 0,250;2:1000,15000` → first band from source 1
  (default), second from source 2.
- New shared helper `automixer/utils.py::slice_source(config, channel, start_ms, length_ms)`
  resolves `config.audio2 if channel.source2 and config.audio2 is not None else config.audio`,
  then **wraps by modulo** on that source's own length — so a shorter or longer source2 still
  produces a full-length slice at any beat-grid position, using the *same* beat grid throughout
  (source2 supplies material, never its own timing).
- All 4 mixers route their per-grain slicing through `slice_source` instead of directly indexing
  `config.audio[...]`. In `library_mixer.py` (which shares one grain across channels, filtered
  differently, rather than drawing independent random grains), a `source2` channel instead pulls
  the **same relative beat-grid position** from source2 via `slice_source` — same "same grid,
  different material" rule, applied post-hoc since that mixer's grain selection precedes the
  per-channel render step.

### 5. Closed-loop Uxn control

- `paramgen.tal`'s argv contract becomes **always 3 tokens, in the order `feedback`, `tick`,
  `macro_tick`** — feedback must arrive **first**, not last: `c`'s string is emitted while
  processing the *first* line the ROM reads, so a feedback value read *after* `c` has already
  been printed could never influence it. Reading order is what the state machine keys off (each
  token is a full newline-terminated line; there is no way to "peek ahead"), so feedback owns
  token-state 0 (stash-only, no emit), tick owns state 1 (existing `l`/`w`/`s`/`c` logic), macro_tick
  keeps state 2 (existing `ss` logic + halt).
- `feedback`'s low 2 bits perturb channel-band selection: at `&cpart`,
  `idx_c = ((tick_lo >> 6) & 3) EOR (feedback_lo & 3)` (a new persistent zero-page byte at `03`
  holds the stashed feedback value across the token-0 → token-1 transition). Because
  `x EOR 0 == x`, passing `feedback=0` is a **true no-op** — today's ROM output is byte-for-byte
  unchanged for any tick when feedback is 0, preserving every existing `test_uxn_stream.py`
  assertion.
- `automixer/uxn_stream.py::uxn_tick` gains a `feedback=0` parameter, always passed as the
  **first** argv token, ahead of `tick`/`macro_tick` (so the ROM's contract is uniform whether or
  not closed-loop is in use).
- `run_uxn_sequence` gains a `closed_loop=False` flag. When `True`, each tick computes a real
  feedback byte from the *current* source: sample a handful of evenly-spaced beat-grid grains,
  measure via the existing `features.measure_grain` (reusing the one measure tract — no new
  analyzer), average `rhythm_density`, clamp/scale to `[0, 255]` (fixed 0–5 onsets/sec range,
  consistent with `features.py`'s existing calibration philosophy of not assuming an unverified
  raw scale... here a fixed practical range is acceptable since it's a coarse 2-bit-consumed
  perturbation, not a precision measurement).
- New CLI flag `--uxn-feedback` (only meaningful with `--uxn-ctrl`) sets `closed_loop=True`.
  Default off — existing `--uxn-ctrl` behavior is completely unchanged unless explicitly opted
  into.
- Requires rebuilding `paramgen.rom` via the vendored `uxn_ctrl/build.sh --rom` after the `.tal`
  edit; the rebuilt ROM is committed (matches how `paramgen.rom` is already committed prebuilt).

### TUI parity

- **Params panel**: new `env` (%) and `rv` (0–1) numeric fields alongside the existing
  `l`/`s`/`ss`/`w` fields.
- **Tracks panel**: per-track "source" selector (A/B), plus a new source-B path/URL field in (or
  beside) the Source panel — same load-on-submit pattern as the primary source, gated the same
  way (`Loading`/`Loaded`/`Failed` messages) so the UI never freezes on the second decode either.
- **Run panel**: new Uxn control section — ROM path (defaults to the vendored `paramgen.rom`),
  tick count, and a closed-loop toggle (`--uxn-feedback` equivalent) — this closes the *existing*
  issue #13 TUI gap, not just the new feedback capability.
- **lib mode**: no new TUI surface needed (HPSS axis is always-on); the existing lib-mode debug/
  info surface, if it names axis count, gets bumped from 3 to 4.

## Testing

- TDD per feature: RED-first tests before implementation, matching the repo's established
  convention (e.g. `test_uxn_stream.py`'s own header note).
- Envelope/reverse: assert grain-boundary energy/click reduction is out of scope for automated
  assertion (perceptual); instead assert the *mechanism* — a `rv 1.0` render's grains are
  measurably reversed (e.g. compare a distinctive onset's position), `env 0` output is
  bit-identical to pre-change behavior (regression guard), `env 50` measurably shapes the
  boundary samples toward silence.
- HPSS axis: assert `measure_grain` returns a 4th key, assert it varies meaningfully across a
  percussive vs. a tonal test fixture (not a constant — same "don't saturate" discipline as the
  other 3 axes).
- Dual-source: assert a `source2`-tagged channel's output actually contains material from
  source2, not source1 (e.g. distinct fixture tones), and that a source2 shorter than the beat
  grid still produces full-length output (wrap, no crash/truncation).
- Uxn feedback: extend `test_uxn_stream.py` — assert `feedback=0` reproduces every existing
  fixture's exact output (the no-op guarantee), and assert a nonzero feedback value changes
  `idx_c`'s selection for at least one tick where it wouldn't have otherwise (a real-effect gate,
  not just "it runs").
- Full existing suite must stay green throughout (regression guard for the whole mixer stack).

## Rollout

Implemented as independent tasks (dispatched to sub-agents): envelope+reverse together (both are
small per-mixer edits touching the same call sites), HPSS axis, dual-source, Uxn feedback, TUI
parity, docs. Reviewed, then committed and pushed to `master` (this repo's existing convention —
recent uxn work also landed direct to master, no PR). A Telegram notification goes out once
everything is merged, pushed, and green.
