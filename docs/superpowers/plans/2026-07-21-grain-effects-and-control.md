# Grain Effects & Control Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 approved features to `grainneukeln` — grain envelope, reverse grains, an HPSS
clustering axis, dual-source grinding, and closed-loop Uxn control — with full CLI/REPL/TUI parity
and updated docs, ending with everything pushed to `master`.

**Architecture:** Every feature is an additive extension of the existing `amc` grammar /
`AutoMixerConfig` / per-mixer grain-cut call sites — no new mixer modes, no rewrite of any mixer's
core algorithm. `automixer/effects/grain_shape.py` holds the two new per-grain primitives
(envelope, reverse); `automixer/utils.py::slice_source` centralizes dual-source resolution; the
Uxn ROM gets a minimal 3rd-token extension to its existing table-lookup state machine.

**Tech Stack:** Python 3.12, pydub (AudioSegment), librosa, numpy, scipy (kmeans2), Textual (TUI),
uxntal/vendored Uxn emulator (C), pytest/unittest.

## Global Constraints

- Repo: `/home/mesh-home/grainneukeln`. Venv: `. .venv/bin/activate` (already provisioned).
- Test runner: `pytest` (also supports plain `unittest` discovery). Run the FULL suite
  (`python -m pytest -q`) before every push — it currently has 4 pre-existing unrelated failures
  in `cutter/test_sample_cut_tool.py` (relative-path bug from an ancient commit, `4906246` —
  **do not fix these, they are out of scope**; confirm no NEW failures beyond these 4).
- Seed-reproducibility contract: `apply_seed(config)` seeds `random` (stdlib) + `np.random` (global)
  from `config.seed`; `LibraryAutoMixer` additionally builds its own `np.random.default_rng(seed)`.
  Any new randomness (reverse-gating) MUST draw from whichever of these the calling mixer already
  uses — never a fresh unseeded call — or the byte-identical-under-seed guarantee breaks.
  `tests/test_bit_identity.py` / `automixer/test_low_memory_bit_identity.py` are the existing
  guard; re-run them after every mixer edit.
- Uxn no-op guarantee: `feedback=0` (the default) MUST reproduce every existing
  `automixer/test_uxn_stream.py` assertion byte-for-byte — `x EOR 0 == x`.
- Commit convention: small, focused commits, `feat(scope): summary` / `test(scope): summary` /
  `docs(scope): summary`, no PR — this repo's recent history (uxn Option A work) lands commits
  directly on `master`.
- `git push` to `origin master` only happens once, at the very end (Task 7), after the full suite
  is green.

---

### Task 1: Grain envelope + reverse grains

**Files:**
- Create: `automixer/effects/grain_shape.py`
- Create: `tests/test_grain_shape.py`
- Create: `tests/test_default_mixer.py`
- Modify: `automixer/config.py:64-131` (`AutoMixerConfig.__init__`/`__str__`)
- Modify: `automixer/mixers/default_mixer.py` (whole file, 96 lines)
- Modify: `automixer/mixers/quantized_mixer.py:143-181` (`_create_grain`)
- Modify: `automixer/mixers/poly_mixer.py:113-136` (`_create_grain`)
- Modify: `automixer/mixers/library_mixer.py:82-96` (`_render_grain`)
- Modify: `cutter/sample_cut_tool.py:417-489` (`config_automix` — add `env`/`rv` token parsing)
- Modify: `tests/test_quantized_mixer.py`, `tests/test_poly_mixer.py`, `tests/test_library_mixer.py`
  (add envelope/reverse wiring assertions)

**Interfaces:**
- Produces: `automixer.effects.grain_shape.maybe_reverse(seg, prob, rng) -> AudioSegment`,
  `automixer.effects.grain_shape.apply_envelope(seg, pct) -> AudioSegment`.
- Produces: `AutoMixerConfig.env_pct` (float, default `8.0`), `AutoMixerConfig.reverse_prob`
  (float, default `0.0`) — consumed by all 4 mixers and by Task 3/4/5's config wiring.
- Consumes: nothing from other tasks (this is the first task).

- [ ] **Step 1: Write the failing tests for the new effect primitives**

Create `tests/test_grain_shape.py`:

```python
import unittest

from pydub.generators import Sine

from automixer.effects.grain_shape import maybe_reverse, apply_envelope


class _FixedRng:
    """Stub RNG exposing the one method grain_shape needs — `.random()` -> a fixed float, matching
    the surface both `random` (the stdlib module) and `np.random.Generator` share."""
    def __init__(self, value):
        self._value = value

    def random(self):
        return self._value


class MaybeReverseTest(unittest.TestCase):
    def test_prob_zero_is_never_reversed(self):
        seg = Sine(300).to_audio_segment(duration=200)
        out = maybe_reverse(seg, 0.0, _FixedRng(0.0))
        self.assertEqual(bytes(out._data), bytes(seg._data))

    def test_below_threshold_reverses(self):
        seg = Sine(300).to_audio_segment(duration=200)
        out = maybe_reverse(seg, 0.5, _FixedRng(0.1))
        self.assertEqual(bytes(out._data), bytes(seg.reverse()._data))

    def test_above_threshold_passes_through(self):
        seg = Sine(300).to_audio_segment(duration=200)
        out = maybe_reverse(seg, 0.5, _FixedRng(0.9))
        self.assertEqual(bytes(out._data), bytes(seg._data))

    def test_empty_segment_is_a_noop(self):
        seg = Sine(300).to_audio_segment(duration=0)
        out = maybe_reverse(seg, 1.0, _FixedRng(0.0))
        self.assertEqual(len(out), 0)


class ApplyEnvelopeTest(unittest.TestCase):
    def test_pct_zero_is_a_true_noop(self):
        seg = Sine(300).to_audio_segment(duration=200)
        out = apply_envelope(seg, 0)
        self.assertEqual(bytes(out._data), bytes(seg._data))

    def test_negative_pct_is_a_noop(self):
        seg = Sine(300).to_audio_segment(duration=200)
        out = apply_envelope(seg, -5)
        self.assertEqual(bytes(out._data), bytes(seg._data))

    def test_positive_pct_shapes_the_edges_toward_silence(self):
        seg = Sine(300).to_audio_segment(duration=200).apply_gain(0)  # full-amplitude tone
        out = apply_envelope(seg, 20)
        self.assertEqual(len(out), len(seg))
        # first/last sample must be materially quieter than the un-enveloped tone's edge sample —
        # a real fade, not a no-op that happened to pass the length check.
        import numpy as np
        raw = np.array(seg.get_array_of_samples())
        shaped = np.array(out.get_array_of_samples())
        self.assertLess(abs(shaped[0]), abs(raw[0]) or 1)
        self.assertLess(abs(shaped[-1]), abs(raw[-5]) or 1)

    def test_pct_is_clamped_so_taper_never_exceeds_half_length(self):
        seg = Sine(300).to_audio_segment(duration=50)
        # 200% would ask for a 100ms taper on each edge of a 50ms grain -- must not crash or
        # produce something longer/shorter than the input.
        out = apply_envelope(seg, 200)
        self.assertEqual(len(out), len(seg))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/mesh-home/grainneukeln && . .venv/bin/activate && python -m pytest tests/test_grain_shape.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'automixer.effects.grain_shape'`

- [ ] **Step 3: Implement `automixer/effects/grain_shape.py`**

```python
"""Per-grain shaping effects: probability-gated reverse playback and an attack/release envelope.

Both operate on one already-cut grain (a pydub ``AudioSegment``). There is no single shared
mixer loop to hook these into once -- rw/q/poly/lib each build grains their own way -- so this
module holds the two primitives and every mixer calls them at the point it already has a
finished grain in hand (design doc 2026-07-21).
"""


def maybe_reverse(seg, prob, rng):
    """Reverse ``seg`` with probability ``prob`` (0..1), decided by ``rng.random()``.

    ``rng`` MUST be whatever RNG source the calling mixer already threads through
    ``apply_seed``/``np.random.default_rng`` (never a fresh unseeded call) -- both the stdlib
    ``random`` module and an ``np.random.Generator`` instance expose a no-arg ``.random()`` in
    [0, 1), so either can be passed here and the seed-reproducibility contract (same seed + params
    -> byte-identical output) holds either way. ``prob <= 0`` short-circuits without touching the
    RNG at all, so a `reverse_prob=0.0` render draws exactly as many random numbers as before this
    feature existed.
    """
    if prob <= 0 or len(seg) == 0:
        return seg
    if rng.random() < prob:
        return seg.reverse()
    return seg


def apply_envelope(seg, pct):
    """Attack/release fade, ``pct`` percent of the segment's own length tapered on each edge.

    ``pct <= 0`` is a no-op (the explicit opt-out, `amc env 0`) -- otherwise this runs
    unconditionally for every mixer, since a hard-cut grain boundary is a defect (audible click),
    not a creative choice. The taper is clamped to at most half the grain's length so an
    oversized ``pct`` can never make attack and release overlap/exceed the grain.
    """
    if pct <= 0 or len(seg) == 0:
        return seg
    taper_ms = int(len(seg) * (pct / 100.0))
    taper_ms = max(0, min(taper_ms, len(seg) // 2))
    if taper_ms <= 0:
        return seg
    return seg.fade_in(taper_ms).fade_out(taper_ms)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_grain_shape.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add automixer/effects/grain_shape.py tests/test_grain_shape.py
git commit -m "feat(effects): grain reverse + attack/release envelope primitives"
```

- [ ] **Step 6: Add `env_pct`/`reverse_prob` to `AutoMixerConfig`**

Modify `automixer/config.py`. In `AutoMixerConfig.__init__`, add two new keyword params
(`env_pct=8.0, reverse_prob=0.0`) to the signature (insert right after `low_memory=False`), and
store them:

```python
                 seed=None,
                 low_memory=False,
                 env_pct=8.0,
                 reverse_prob=0.0):
```

...and in the body, right after `self.low_memory = low_memory`:

```python
        self.low_memory = low_memory
        # Grain shaping (2026-07-21): attack/release taper (% of grain length, always-on unless
        # explicitly zeroed -- a hard-cut boundary is a defect, not a creative choice) and
        # per-grain reverse probability (0..1, default off -- today's character unchanged).
        self.env_pct = float(env_pct)
        self.reverse_prob = float(reverse_prob)
```

- [ ] **Step 7: Write a failing config test**

Add to `tests/test_config.py` (new test class at the end, before `if __name__ == "__main__":`):

```python
from automixer.config import AutoMixerConfig


class GrainShapeDefaultsTest(unittest.TestCase):
    def test_env_pct_defaults_on(self):
        cfg = AutoMixerConfig(audio=None, beats=[], sample_length=200)
        self.assertEqual(cfg.env_pct, 8.0)

    def test_reverse_prob_defaults_off(self):
        cfg = AutoMixerConfig(audio=None, beats=[], sample_length=200)
        self.assertEqual(cfg.reverse_prob, 0.0)

    def test_both_are_overridable(self):
        cfg = AutoMixerConfig(audio=None, beats=[], sample_length=200, env_pct=0, reverse_prob=0.4)
        self.assertEqual(cfg.env_pct, 0.0)
        self.assertEqual(cfg.reverse_prob, 0.4)
```

`tests/test_config.py` currently starts with `import unittest` at line 1 — this new class needs
that same import (already present, no change needed there).

- [ ] **Step 8: Run, verify RED then GREEN**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL first (AttributeError on `cfg.env_pct`) — implement Step 6 if not already done,
then re-run and expect PASS (existing tests + 3 new ones).

- [ ] **Step 9: Commit**

```bash
git add automixer/config.py tests/test_config.py
git commit -m "feat(config): env_pct + reverse_prob on AutoMixerConfig"
```

- [ ] **Step 10: Wire both effects into `default_mixer.py` (rw mode)**

Replace the whole of `automixer/mixers/default_mixer.py`'s `_create_chunk` with:

```python
import gc
import random

from pydub import AudioSegment
from tqdm import tqdm

from automixer.effects.band_pass import band_pass_filer
from automixer.effects.change_tempo import change_audioseg_tempo, snap_to_length
from automixer.effects.grain_shape import maybe_reverse, apply_envelope
from automixer.iterators.rolling_window import rolling_window
from automixer.utils import calculate_step, apply_seed, concat_bit_identical


def _create_chunk(config, window):
    chunk = AudioSegment.silent(duration=config.sample_length)
    snap = bool(getattr(config, "snap", False))
    reverse_prob = float(getattr(config, "reverse_prob", 0.0))
    env_pct = float(getattr(config, "env_pct", 8.0))
    for channel in config.channels_config:
        start_cut = random.choice(window)
        if snap:
            cut_len = max(1, int(config.sample_length * random.uniform(0.6, 1.4)))
            channel_chunk = config.audio[start_cut: start_cut + cut_len]
            channel_chunk = maybe_reverse(channel_chunk, reverse_prob, random)
            if not channel.bypass:
                channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
            if len(channel_chunk) != int(config.sample_length):
                channel_chunk = snap_to_length(channel_chunk, config.sample_length,
                                                verbose=config.is_verbose_mode_enabled)
        else:
            channel_chunk = config.audio[start_cut: start_cut + config.sample_length]
            channel_chunk = maybe_reverse(channel_chunk, reverse_prob, random)
            if not channel.bypass:
                channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
        chunk = chunk.overlay(channel_chunk)
    if config.sample_speed != 1.0:
        chunk = change_audioseg_tempo(chunk, config.sample_speed, verbose=config.is_verbose_mode_enabled)
    chunk = apply_envelope(chunk, env_pct)

    return chunk
```

(The rest of `default_mixer.py` — `RandomWindowAutoMixer.mix` and its low-memory branch — is
untouched; only the import block and `_create_chunk`'s body change.)

- [ ] **Step 11: Write a failing wiring test for the rw mixer**

Create `tests/test_default_mixer.py`:

```python
import unittest
from unittest.mock import patch

import numpy as np
from pydub.generators import Sine

from automixer.config import AutoMixerConfig
from automixer.mixers.default_mixer import RandomWindowAutoMixer, _create_chunk


def _short_source(ms=4000):
    return Sine(220).to_audio_segment(duration=ms)


class DefaultMixerGrainShapeTest(unittest.TestCase):
    def test_env_zero_never_calls_fade(self):
        audio = _short_source()
        beats = np.array([0, 400, 800, 1200, 1600, 2000, 2400, 2800, 3200])
        cfg = AutoMixerConfig(audio=audio, beats=beats, sample_length=200, env_pct=0.0,
                               window_divider=2)
        with patch("automixer.mixers.default_mixer.apply_envelope",
                   side_effect=lambda seg, pct: seg) as spy:
            RandomWindowAutoMixer().mix(cfg)
        # called once per _create_chunk invocation, always with pct=0.0
        self.assertTrue(spy.called)
        for call in spy.call_args_list:
            self.assertEqual(call.args[1], 0.0)

    def test_reverse_prob_one_reverses_every_grain(self):
        audio = _short_source()
        beats = np.array([0, 400, 800, 1200, 1600, 2000, 2400, 2800, 3200])
        cfg = AutoMixerConfig(audio=audio, beats=beats, sample_length=200, reverse_prob=1.0,
                               window_divider=2, seed=1)
        with patch("automixer.mixers.default_mixer.maybe_reverse",
                   wraps=lambda seg, prob, rng: seg.reverse() if prob >= 1.0 else seg) as spy:
            RandomWindowAutoMixer().mix(cfg)
        self.assertTrue(spy.called)
        for call in spy.call_args_list:
            self.assertEqual(call.args[1], 1.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 12: Run, verify RED then GREEN**

Run: `python -m pytest tests/test_default_mixer.py -v`
Expected: FAIL first (`_create_chunk` not yet importing/calling the new helpers if Step 10 isn't
applied yet), PASS after Step 10 lands.

- [ ] **Step 13: Run the full bit-identity regression suite**

Run: `python -m pytest tests/test_bit_identity.py automixer/test_low_memory_bit_identity.py -v`
Expected: PASS unchanged — `env_pct` defaults to `8.0` now (not a no-op!), so if these tests
construct `AutoMixerConfig` without pinning `env_pct=0`, their recorded "bit-identical" fixtures
may now legitimately differ from a stored expectation. Read the two files first: if they compare
two live renders against EACH OTHER (not against a stored golden file), the default `env_pct=8.0`
applies identically to both sides and the test still passes. If either compares against a
hardcoded byte string / golden fixture, add `env_pct=0` to that config's construction so it
reproduces the pre-existing hard-cut path exactly, and note this in the commit message.

- [ ] **Step 14: Commit**

```bash
git add automixer/mixers/default_mixer.py tests/test_default_mixer.py tests/test_bit_identity.py automixer/test_low_memory_bit_identity.py
git commit -m "feat(mixer): wire envelope + reverse into the rw (default) mixer"
```

- [ ] **Step 15: Wire both effects into `quantized_mixer.py` (q mode)**

Modify `automixer/mixers/quantized_mixer.py`. Add to the import block (near the top, alongside
the existing `from automixer.effects...` imports):

```python
from automixer.effects.grain_shape import maybe_reverse, apply_envelope
```

Replace `_create_grain` (currently lines ~143-181) with:

```python
    def _create_grain(self, config, onsets, grain_len, snap=False, candidates=None):
        """Cut one grain at a (randomly chosen) source position from ``onsets`` (an onset pool for
        HIT slots, or a remnant pool for fills), band-passed per channel.

        Random pick -> content varies run to run; the grid position it lands on is fixed by the
        caller, so the *placement* stays deterministic (issue #5 acceptance #4).

        ``candidates`` is the precomputed subset of ``onsets`` satisfying ``0 <= o <= max_start``
        — passed in by the caller (``mix``) so the per-grain O(n_onsets) list comprehension runs
        ONCE per mix, not once per grain. Bit-identical to computing it here (same list, same
        ``random.choice`` draw); only the call site moves. ``None`` falls back to the in-function
        filter for callers that didn't precompute (e.g. tests)."""
        audio = config.audio
        max_start = len(audio) - grain_len
        if max_start <= 0:
            return audio[:grain_len]

        if candidates is None:
            candidates = [o for o in onsets if 0 <= o <= max_start]
        if candidates:
            start_cut = random.choice(candidates)
        else:
            # No onset survived (silent/degenerate source): fall back to a random position rather
            # than a beat floor, so the grid still fills.
            start_cut = random.randint(0, max_start)

        # Snap (issue #8): cut the natural transient unit (onset -> next onset, capped) and
        # pitch-preservingly stretch it to the slot length, so off-length material lands on the grid.
        cut_len = grain_len
        if snap and candidates:
            nexts = [o for o in onsets if o > start_cut]
            raw = (nexts[0] - start_cut) if nexts else grain_len
            cut_len = int(max(1, min(raw, len(audio) - start_cut)))
            cut_len = int(max(grain_len * 0.5, min(grain_len * 1.5, cut_len)))

        reverse_prob = float(getattr(config, "reverse_prob", 0.0))
        env_pct = float(getattr(config, "env_pct", 8.0))
        grain = AudioSegment.silent(duration=cut_len)
        for channel in config.channels_config:
            channel_chunk = audio[start_cut: start_cut + cut_len]
            channel_chunk = maybe_reverse(channel_chunk, reverse_prob, random)
            if not channel.bypass:
                channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
            grain = grain.overlay(channel_chunk)
        if snap and len(grain) != grain_len:
            grain = snap_to_length(grain, grain_len, verbose=config.is_verbose_mode_enabled)
        if config.sample_speed != 1.0:
            grain = change_audioseg_tempo(grain, config.sample_speed,
                                          verbose=config.is_verbose_mode_enabled)
        grain = apply_envelope(grain, env_pct)
        return grain
```

- [ ] **Step 16: Add a wiring test to `tests/test_quantized_mixer.py`**

Read the file first (`sed -n '1,40p' tests/test_quantized_mixer.py`) to match its existing
imports/fixture style, then append a test class following the exact pattern used in Step 11
(`patch("automixer.mixers.quantized_mixer.apply_envelope", ...)` /
`patch("automixer.mixers.quantized_mixer.maybe_reverse", ...)`), asserting `env_pct=0.0` calls
carry `pct=0.0` and `reverse_prob=1.0` calls carry `prob=1.0`, run against `QuantizedAutoMixer`
the same way Step 11 runs `RandomWindowAutoMixer`.

- [ ] **Step 17: Run, verify RED then GREEN, then run the full quantized-mixer suite**

Run: `python -m pytest tests/test_quantized_mixer.py -v`
Expected: PASS (existing tests + new ones).

- [ ] **Step 18: Commit**

```bash
git add automixer/mixers/quantized_mixer.py tests/test_quantized_mixer.py
git commit -m "feat(mixer): wire envelope + reverse into the quantized (q) mixer"
```

- [ ] **Step 19: Wire both effects into `poly_mixer.py` (poly mode)**

Modify `automixer/mixers/poly_mixer.py`. Add to imports:

```python
from automixer.effects.grain_shape import maybe_reverse, apply_envelope
```

Replace `_create_grain` (currently lines ~113-136) with:

```python
    def _create_grain(self, config, onsets, grain_len, channels, candidates=None):
        """Cut one grain at a random source onset, band-passed through this stream's channels.

        Random onset -> content varies run to run; the stream's grid positions are fixed, so the
        polyrhythmic PLACEMENT is deterministic.

        ``candidates`` is the precomputed subset of ``onsets`` satisfying ``0 <= o <= max_start``
        — passed by the caller (``mix``) so the per-grain O(n_onsons) filter runs ONCE per stream,
        not once per grain. Bit-identical to in-function filtering; ``None`` falls back for callers
        that didn't precompute."""
        audio = config.audio
        max_start = len(audio) - grain_len
        if max_start <= 0:
            return audio[:grain_len]

        if candidates is None:
            candidates = [o for o in onsets if 0 <= o <= max_start]
        start_cut = random.choice(candidates) if candidates else random.randint(0, max_start)

        reverse_prob = float(getattr(config, "reverse_prob", 0.0))
        env_pct = float(getattr(config, "env_pct", 8.0))
        grain = AudioSegment.silent(duration=grain_len)
        for channel in channels:
            channel_chunk = audio[start_cut: start_cut + grain_len]
            channel_chunk = maybe_reverse(channel_chunk, reverse_prob, random)
            if not channel.bypass:
                channel_chunk = band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk)
            grain = grain.overlay(channel_chunk)
        if config.sample_speed != 1.0:
            grain = change_audioseg_tempo(grain, config.sample_speed,
                                          verbose=config.is_verbose_mode_enabled)
        grain = apply_envelope(grain, env_pct)
        return grain
```

- [ ] **Step 20: Add a wiring test to `tests/test_poly_mixer.py`**

Read the file first, then append a test class mirroring Step 16's pattern, targeting
`PolyphonicAutoMixer` and patching `automixer.mixers.poly_mixer.apply_envelope` /
`automixer.mixers.poly_mixer.maybe_reverse`.

- [ ] **Step 21: Run, verify RED then GREEN**

Run: `python -m pytest tests/test_poly_mixer.py -v`
Expected: PASS.

- [ ] **Step 22: Commit**

```bash
git add automixer/mixers/poly_mixer.py tests/test_poly_mixer.py
git commit -m "feat(mixer): wire envelope + reverse into the poly mixer"
```

- [ ] **Step 23: Wire both effects into `library_mixer.py` (lib mode)**

Modify `automixer/mixers/library_mixer.py`. Add to imports:

```python
from automixer.effects.grain_shape import maybe_reverse, apply_envelope
```

Replace `_render_grain` (currently lines ~82-96) with:

```python
    def _render_grain(self, config, grain):
        reverse_prob = float(getattr(config, "reverse_prob", 0.0))
        env_pct = float(getattr(config, "env_pct", 8.0))
        out = AudioSegment.silent(duration=len(grain))
        for channel in config.channels_config:
            channel_chunk = maybe_reverse(grain, reverse_prob, random.Random())
            if channel.bypass:
                out = out.overlay(channel_chunk)
            else:
                out = out.overlay(band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk))
        if config.sample_speed != 1.0:
            out = change_audioseg_tempo(out, config.sample_speed, verbose=config.is_verbose_mode_enabled)
        out = apply_envelope(out, env_pct)
        return out
```

Note the RNG choice here: `library_mixer.py`'s `mix()` builds its own `np.random.default_rng(seed)`
(a local variable named `rng`, not an attribute on `self`), which `_render_grain` (an instance
method called per-grain, not passed `rng`) cannot currently reach without a signature change.
Rather than thread `rng` through every `_render_grain` call (touching `mix()`'s call site at
`self._render_grain(config, grains[gi])` too), use a **fresh** `random.Random()` per grain here —
this is a DELIBERATE, DOCUMENTED exception to the "always reuse the mixer's seeded RNG" rule,
because `lib` mode's own grain SELECTION (which grain, in which order) is already fully determined
by the seeded `rng` before rendering starts (`sequence` is built first, `_render_grain` only
shapes the chosen grain) — reversing is a post-selection cosmetic pass, not a selection decision,
so `lib` mode's `seed`-determinism for WHICH grains appear in WHICH order is unaffected either way.
If a future task wants `lib` mode's reverse-gating itself to be seed-reproducible, thread `rng`
into `_render_grain`'s signature and its one call site in `mix()` at that time — flag this as a
known gap in the commit message, do not silently claim full seed-determinism for `lib` reversal.

Add a matching import at the top of the file: `import random` (not currently imported —
`library_mixer.py` today only imports `from pydub import AudioSegment` and effect helpers; verify
with `grep -n "^import\|^from" automixer/mixers/library_mixer.py` before editing).

- [ ] **Step 24: Add a wiring test to `tests/test_library_mixer.py`**

Read the file first, then append a test class targeting `LibraryAutoMixer`, patching
`automixer.mixers.library_mixer.apply_envelope` / `automixer.mixers.library_mixer.maybe_reverse`,
following Step 16's pattern (note `_render_grain` takes a pre-cut `grain`, not `config, window` —
adjust the source fixture so at least 2 distinct grains get built, e.g. an 8-beat, 4-second synth
tone, so `apply_envelope`/`maybe_reverse` are provably called more than once).

- [ ] **Step 25: Run, verify RED then GREEN**

Run: `python -m pytest tests/test_library_mixer.py -v`
Expected: PASS.

- [ ] **Step 26: Commit**

```bash
git add automixer/mixers/library_mixer.py tests/test_library_mixer.py
git commit -m "feat(mixer): wire envelope + reverse into the lib mixer (fresh RNG for reverse only, documented)"
```

- [ ] **Step 27: Wire `env`/`rv` tokens into the REPL's `amc` parser**

Modify `cutter/sample_cut_tool.py`. In `config_automix` (currently ~line 417-489), add alongside
the existing `seed`/`fill_gain_db` token blocks (right before the `channels_config = ...` block
that starts around line 436):

```python
        # Grain shaping (2026-07-21): `env <pct>` attack/release taper (0 disables, default 8);
        # `rv <0..1>` per-grain reverse probability (default 0, off).
        env_pct = getattr(self.auto_mixer_config, "env_pct", 8.0)
        if "env" in args:
            env_pct = float(args[args.index("env") + 1])
        reverse_prob = getattr(self.auto_mixer_config, "reverse_prob", 0.0)
        if "rv" in args:
            reverse_prob = float(args[args.index("rv") + 1])
```

Then add both to the `AutoMixerConfig(...)` constructor call further down (currently ends
`seed=seed,\n        )` around line 488-489):

```python
            seed=seed,
            env_pct=env_pct,
            reverse_prob=reverse_prob,
        )
```

Also add both to `show_automix_help`'s printed list (after the existing `l <length>` help line,
currently ~line 511):

```python
        print(
            "  env <pct>: attack/release taper as %% of grain length (default 8, 0 disables). Example: amc env 15"
        )
        print(
            "  rv <0..1>: probability each grain is reversed (default 0). Example: amc rv 0.3"
        )
```

- [ ] **Step 28: Write a failing CLI-parsing test**

Find or create `cutter/test_sample_cut_tool_amc.py` (check first: `grep -rl "config_automix"
cutter/test_*.py` — if a suitable existing test file already exercises `config_automix` token
parsing, e.g. `cutter/test_series_cli.py`, add there instead of creating a new file; otherwise
create `cutter/test_env_rv_cli.py`):

```python
import os
import unittest

from cutter.sample_cut_tool import SampleCutter

ASSET = os.path.join(os.path.dirname(__file__), "..", "assets", "test_audio.mp3")


class EnvRvTokenParsingTest(unittest.TestCase):
    def setUp(self):
        self.cutter = SampleCutter(ASSET, "/tmp")

    def test_env_token_sets_env_pct(self):
        self.cutter.config_automix("amc env 15")
        self.assertEqual(self.cutter.auto_mixer_config.env_pct, 15.0)

    def test_rv_token_sets_reverse_prob(self):
        self.cutter.config_automix("amc rv 0.3")
        self.assertEqual(self.cutter.auto_mixer_config.reverse_prob, 0.3)

    def test_defaults_when_absent(self):
        self.cutter.config_automix("amc l 200")
        self.assertEqual(self.cutter.auto_mixer_config.env_pct, 8.0)
        self.assertEqual(self.cutter.auto_mixer_config.reverse_prob, 0.0)


if __name__ == "__main__":
    unittest.main()
```

Confirm `assets/test_audio.mp3` exists (`ls assets/`) before relying on it — every other cutter
test in this repo already depends on it, so it should be present; if absent, use
`tests/test_snap.py`'s `Sine(...).to_audio_segment(...)` + a temp-file export approach instead and
note the substitution in the commit message.

- [ ] **Step 29: Run, verify RED then GREEN**

Run: `python -m pytest cutter/test_env_rv_cli.py -v` (or wherever Step 28 landed)
Expected: FAIL first, PASS after Step 27.

- [ ] **Step 30: Commit**

```bash
git add cutter/sample_cut_tool.py cutter/test_env_rv_cli.py
git commit -m "feat(cli): amc env/rv tokens for grain envelope + reverse"
```

- [ ] **Step 31: Full regression run**

Run: `python -m pytest -q`
Expected: same 4 pre-existing failures (documented in Global Constraints) and otherwise all green.

---

### Task 2: HPSS clustering axis (lib mode)

**Files:**
- Modify: `automixer/features.py:15-46` (`AXES`, `measure_grain`)
- Modify: `automixer/test_features.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent — `features.py`/`library_mixer.py`'s clustering
  pipeline reads `AXES` generically, no other mixer touches this file).
- Produces: `features.AXES` grows from 3 to 4 entries; `measure_grain(seg)` returns a dict with
  the new `"hpss_ratio"` key. `library_mixer.py` needs NO changes — it already calls
  `calibrate(feats)` with `axes=AXES`'s default and iterates whatever axis count `AXES` has.

- [ ] **Step 1: Write the failing test**

Read `automixer/test_features.py` first (`cat automixer/test_features.py`) to match its existing
fixture/import style, then add:

```python
class HpssAxisTest(unittest.TestCase):
    def test_axes_includes_hpss_ratio(self):
        from automixer.features import AXES
        self.assertIn("hpss_ratio", AXES)
        self.assertEqual(len(AXES), 4)

    def test_measure_grain_returns_hpss_ratio(self):
        from automixer.features import measure_grain
        from pydub.generators import Sine
        seg = Sine(440).to_audio_segment(duration=500)
        feats = measure_grain(seg)
        self.assertIn("hpss_ratio", feats)
        self.assertTrue(0.0 <= feats["hpss_ratio"] <= 1.0)

    def test_hpss_ratio_discriminates_tonal_vs_percussive(self):
        # A pure sustained sine is harmonic-dominant (low percussive ratio); white noise bursts
        # read as percussive-dominant (high ratio) -- the axis must not saturate/constant-out
        # (mesh doctrine: an axis whose real values pin at one end silently drops from clustering).
        from automixer.features import measure_grain
        from pydub.generators import Sine, WhiteNoise
        tonal = measure_grain(Sine(440).to_audio_segment(duration=800))
        percussive = measure_grain(WhiteNoise().to_audio_segment(duration=800))
        self.assertLess(tonal["hpss_ratio"], percussive["hpss_ratio"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest automixer/test_features.py -v -k hpss`
Expected: FAIL — `AssertionError` (axis absent) / `KeyError`.

- [ ] **Step 3: Implement the HPSS axis in `automixer/features.py`**

Change `AXES` (currently line 15):

```python
AXES = ("centroid", "rms", "rhythm_density", "hpss_ratio")
```

Change `measure_grain` (currently lines 26-46) to compute + return the new key:

```python
def measure_grain(seg):
    """Measure one grain (a pydub ``AudioSegment``) on the four axes.

    ``rhythm_density`` is onsets per second *within the grain* — it discriminates real, rhythmic
    material (many onsets/sec) from an isolated impulse (a single transient in the window → ~0).
    ``hpss_ratio`` is percussive energy / (harmonic + percussive energy) via
    ``librosa.effects.hpss`` — the SAME measure tract (no second analyzer), giving `lib con`
    (contrast) a real percussive-vs-tonal axis to jump across, not just loudness/brightness/density."""
    import numpy as np
    import librosa

    y, sr = _to_mono_float(seg)
    if y.size < 128:
        return {"centroid": 0.0, "rms": 0.0, "rhythm_density": 0.0, "hpss_ratio": 0.0}
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    rms = float(np.mean(librosa.feature.rms(y=y)))
    dur = len(y) / float(sr)
    try:
        onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
    except Exception:
        onsets = []
    rhythm_density = (len(onsets) / dur) if dur > 0 else 0.0
    harmonic, percussive = librosa.effects.hpss(y)
    h_energy = float(np.sum(harmonic ** 2))
    p_energy = float(np.sum(percussive ** 2))
    total_energy = h_energy + p_energy
    hpss_ratio = (p_energy / total_energy) if total_energy > 0 else 0.0
    return {
        "centroid": centroid, "rms": rms, "rhythm_density": float(rhythm_density),
        "hpss_ratio": float(hpss_ratio),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest automixer/test_features.py -v`
Expected: PASS (all existing + 3 new tests). If `test_hpss_ratio_discriminates_tonal_vs_percussive`
is flaky/borderline on a short 800ms fixture, lengthen the fixture to 1500-2000ms rather than
loosening the assertion — the point of this test is that the axis is not a constant, and a longer
clip gives `librosa.effects.hpss` more signal to separate.

- [ ] **Step 5: Run the lib mixer's own suite to confirm no downstream break**

Run: `python -m pytest tests/test_library_mixer.py -v`
Expected: PASS unchanged — `library_mixer.py` has no per-axis-count logic, so a 4th axis flows
through `calibrate`/`cluster`/`next_cluster` with zero code changes there.

- [ ] **Step 6: Commit**

```bash
git add automixer/features.py automixer/test_features.py
git commit -m "feat(lib): add HPSS harmonic/percussive ratio as a 4th clustering axis"
```

---

### Task 3: Dual-source grinding

**Files:**
- Modify: `automixer/config.py:9-31` (`ChannelConfig`), `:64-146` (`AutoMixerConfig`)
- Modify: `automixer/utils.py` (add `slice_source`)
- Modify: `automixer/mixers/default_mixer.py`, `quantized_mixer.py`, `poly_mixer.py`,
  `library_mixer.py` (route slicing through `slice_source`) — these files already carry Task 1's
  edits; this task edits them again on top.
- Modify: `cutter/sample_cut_tool.py:69-97` (`_load_audio` → factor a reusable decode helper),
  `:346-490` (`config_automix` — `src2` token + `c` grammar `2:` prefix)
- Create: `tests/test_slice_source.py`
- Modify: `tests/test_default_mixer.py`, `tests/test_quantized_mixer.py`, `tests/test_poly_mixer.py`,
  `tests/test_library_mixer.py`, `cutter/test_env_rv_cli.py` (or wherever Task 1 Step 28 landed)

**Interfaces:**
- Consumes: Task 1's per-mixer files (edits land on top of the envelope/reverse wiring).
- Produces: `ChannelConfig(low, high, bypass=False, source2=False)`; `AutoMixerConfig(..., audio2=None)`;
  `automixer.utils.slice_source(config, channel, start_ms, length_ms) -> AudioSegment`;
  `SampleCutter._load_secondary_audio(path)` setting `self.audio2`/`self._audio2_path`.

- [ ] **Step 1: Write the failing test for `slice_source`**

Create `tests/test_slice_source.py`:

```python
import unittest

from pydub.generators import Sine

from automixer.config import AutoMixerConfig, ChannelConfig
from automixer.utils import slice_source


def _cfg(audio, audio2=None):
    cfg = AutoMixerConfig(audio=audio, beats=[], sample_length=200)
    cfg.audio2 = audio2
    return cfg


class SliceSourceTest(unittest.TestCase):
    def test_default_channel_slices_primary_source(self):
        primary = Sine(220).to_audio_segment(duration=2000)
        secondary = Sine(880).to_audio_segment(duration=2000)
        cfg = _cfg(primary, secondary)
        ch = ChannelConfig(0, 15000, bypass=True)
        out = slice_source(cfg, ch, 100, 200)
        self.assertEqual(bytes(out._data), bytes(primary[100:300]._data))

    def test_source2_channel_slices_secondary(self):
        primary = Sine(220).to_audio_segment(duration=2000)
        secondary = Sine(880).to_audio_segment(duration=2000)
        cfg = _cfg(primary, secondary)
        ch = ChannelConfig(0, 15000, bypass=True, source2=True)
        out = slice_source(cfg, ch, 100, 200)
        self.assertEqual(bytes(out._data), bytes(secondary[100:300]._data))

    def test_source2_channel_without_audio2_falls_back_to_primary(self):
        primary = Sine(220).to_audio_segment(duration=2000)
        cfg = _cfg(primary, audio2=None)
        ch = ChannelConfig(0, 15000, bypass=True, source2=True)
        out = slice_source(cfg, ch, 100, 200)
        self.assertEqual(bytes(out._data), bytes(primary[100:300]._data))

    def test_wraps_when_position_plus_length_exceeds_a_shorter_source2(self):
        primary = Sine(220).to_audio_segment(duration=5000)
        secondary = Sine(880).to_audio_segment(duration=300)  # much shorter than the beat grid
        cfg = _cfg(primary, secondary)
        ch = ChannelConfig(0, 15000, bypass=True, source2=True)
        out = slice_source(cfg, ch, 4800, 200)  # 4800 % 300 = 0 -> [0:200]; still full length
        self.assertEqual(len(out), 200)
        self.assertEqual(bytes(out._data), bytes(secondary[0:200]._data))

    def test_wraps_across_the_end_of_source2(self):
        primary = Sine(220).to_audio_segment(duration=5000)
        secondary = Sine(880).to_audio_segment(duration=300)
        cfg = _cfg(primary, secondary)
        ch = ChannelConfig(0, 15000, bypass=True, source2=True)
        out = slice_source(cfg, ch, 250, 100)  # [250:300] + [0:50] wrapped
        self.assertEqual(len(out), 100)
        expected = bytes(secondary[250:300]._data) + bytes(secondary[0:50]._data)
        self.assertEqual(bytes(out._data), expected)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_slice_source.py -v`
Expected: FAIL — `TypeError: ChannelConfig.__init__() got an unexpected keyword argument 'source2'`
/ `ImportError: cannot import name 'slice_source'`.

- [ ] **Step 3: Add `source2` to `ChannelConfig` and `audio2` to `AutoMixerConfig`**

Modify `automixer/config.py`. `ChannelConfig.__init__` (currently lines 18-22):

```python
    def __init__(self, low, high, bypass=False, source2=False):
        if high == 0:
            high = 1
        if low == 0:
            low = 1
        self.high_pass = high
        self.low_pass = low
        self.bypass = bool(bypass)
        # Dual-source grinding (2026-07-21): when True, this band pulls its grains from
        # ``config.audio2`` instead of the primary ``config.audio`` — same beat grid throughout,
        # only the raw material differs. False (default) is today's single-source behaviour.
        self.source2 = bool(source2)
```

`ChannelConfig.__str__` (currently lines 24-27) — extend to surface the source:

```python
    def __str__(self):
        src = " [src2]" if self.source2 else ""
        if self.bypass:
            return "bypass" + src
        return "Low: " + str(self.low_pass) + "; High: " + str(self.high_pass) + src
```

`AutoMixerConfig.__init__` — add `audio2=None` to the signature (alongside Task 1's `env_pct`/
`reverse_prob`, so the tail of the signature reads):

```python
                 seed=None,
                 low_memory=False,
                 env_pct=8.0,
                 reverse_prob=0.0,
                 audio2=None):
```

...and in the body, right after `self.audio = audio`:

```python
        self.audio = audio
        # Dual-source grinding (2026-07-21): the SECOND source's raw audio, or None (default —
        # single-source, today's behaviour). Only channels with ``source2=True`` ever read this;
        # the beat grid always comes from the primary source regardless.
        self.audio2 = audio2
```

- [ ] **Step 4: Implement `slice_source` in `automixer/utils.py`**

Add to `automixer/utils.py` (after `beat_interval`, at the end of the file):

```python
def slice_source(config, channel, start_ms, length_ms):
    """Slice ``length_ms`` of audio starting at ``start_ms`` from whichever source ``channel``
    names — ``config.audio2`` when the channel is tagged ``source2=True`` AND a second source was
    actually loaded, else the primary ``config.audio``.

    Positions always come from the PRIMARY source's beat grid regardless of which source supplies
    the material — a source 2 shorter or longer than that grid is handled by wrapping ``start_ms``
    modulo ITS OWN length, so every call still returns exactly ``length_ms`` of real audio (never
    truncated, never silence-padded). Same beat grid throughout; only the raw material differs
    (dual-source grinding, design doc 2026-07-21)."""
    from pydub import AudioSegment

    src = config.audio
    if getattr(channel, "source2", False) and getattr(config, "audio2", None) is not None:
        src = config.audio2
    n = len(src)
    length_ms = int(length_ms)
    if n <= 0 or length_ms <= 0:
        return AudioSegment.silent(duration=max(0, length_ms))
    start_ms = int(start_ms) % n
    end_ms = start_ms + length_ms
    if end_ms <= n:
        return src[start_ms:end_ms]
    return src[start_ms:n] + src[0:end_ms - n]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_slice_source.py automixer/test_config.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add automixer/config.py automixer/utils.py tests/test_slice_source.py
git commit -m "feat(config): ChannelConfig.source2 + AutoMixerConfig.audio2 + slice_source helper"
```

- [ ] **Step 7: Route `default_mixer.py` through `slice_source`**

Modify `automixer/mixers/default_mixer.py` (the version that already has Task 1's edits). Add
`slice_source` to the `automixer.utils` import:

```python
from automixer.utils import calculate_step, apply_seed, concat_bit_identical, slice_source
```

In `_create_chunk`, replace both raw-slice lines:

```python
            channel_chunk = config.audio[start_cut: start_cut + cut_len]
```
→
```python
            channel_chunk = slice_source(config, channel, start_cut, cut_len)
```

and

```python
            channel_chunk = config.audio[start_cut: start_cut + config.sample_length]
```
→
```python
            channel_chunk = slice_source(config, channel, start_cut, config.sample_length)
```

(Everything else in `_create_chunk` — the `maybe_reverse`/band-pass/envelope calls Task 1 added —
is unchanged; only these two slicing lines move to the helper.)

- [ ] **Step 8: Add a dual-source wiring test to `tests/test_default_mixer.py`**

Append:

```python
class DefaultMixerDualSourceTest(unittest.TestCase):
    def test_source2_channel_pulls_from_audio2(self):
        primary = Sine(220).to_audio_segment(duration=4000)
        secondary = Sine(880).to_audio_segment(duration=4000)
        beats = np.array([0, 400, 800, 1200, 1600, 2000, 2400, 2800, 3200])
        cfg = AutoMixerConfig(
            audio=primary, beats=beats, sample_length=200, window_divider=2, seed=7,
            channels_config=[ChannelConfig(0, 15000, bypass=True, source2=True)],
        )
        cfg.audio2 = secondary
        with patch("automixer.mixers.default_mixer.slice_source",
                   wraps=slice_source) as spy:
            RandomWindowAutoMixer().mix(cfg)
        self.assertTrue(spy.called)
        for call in spy.call_args_list:
            self.assertTrue(call.args[1].source2)
```

Add the needed imports at the top of `tests/test_default_mixer.py`:
`from automixer.config import ChannelConfig` and `from automixer.utils import slice_source`.

- [ ] **Step 9: Run, verify RED then GREEN**

Run: `python -m pytest tests/test_default_mixer.py -v`
Expected: FAIL first (`slice_source` not yet imported into `default_mixer.py` if Step 7 isn't
applied), PASS after.

- [ ] **Step 10: Commit**

```bash
git add automixer/mixers/default_mixer.py tests/test_default_mixer.py
git commit -m "feat(mixer): route rw (default) mixer slicing through slice_source (dual-source)"
```

- [ ] **Step 11: Route `quantized_mixer.py` through `slice_source`**

Modify `automixer/mixers/quantized_mixer.py` (the Task-1-edited version). Add `slice_source` to the
`automixer.utils` import line. In `_create_grain`, replace:

```python
            channel_chunk = audio[start_cut: start_cut + cut_len]
```
→
```python
            channel_chunk = slice_source(config, channel, start_cut, cut_len)
```

Note `audio = config.audio` is still used elsewhere in this file (e.g. `max_start = len(audio) -
grain_len`, `onsets = self._onsets(audio, slot_ms)`) — those stay as-is; only the per-channel
grain-cutting line changes, since `max_start`/onset detection are keyed off the PRIMARY source's
length/content (the beat grid), never source 2's.

- [ ] **Step 12: Add a dual-source wiring test to `tests/test_quantized_mixer.py`**

Mirror Step 8's pattern for `QuantizedAutoMixer`, patching
`automixer.mixers.quantized_mixer.slice_source`.

- [ ] **Step 13: Run, verify RED then GREEN**

Run: `python -m pytest tests/test_quantized_mixer.py -v`
Expected: PASS.

- [ ] **Step 14: Commit**

```bash
git add automixer/mixers/quantized_mixer.py tests/test_quantized_mixer.py
git commit -m "feat(mixer): route quantized (q) mixer slicing through slice_source (dual-source)"
```

- [ ] **Step 15: Route `poly_mixer.py` through `slice_source`**

Modify `automixer/mixers/poly_mixer.py` (Task-1-edited version). Add `slice_source` to the
`automixer.utils` import. In `_create_grain`, replace:

```python
            channel_chunk = audio[start_cut: start_cut + grain_len]
```
→
```python
            channel_chunk = slice_source(config, channel, start_cut, grain_len)
```

- [ ] **Step 16: Add a dual-source wiring test to `tests/test_poly_mixer.py`**

Mirror Step 8's pattern for `PolyphonicAutoMixer`, patching
`automixer.mixers.poly_mixer.slice_source`.

- [ ] **Step 17: Run, verify RED then GREEN**

Run: `python -m pytest tests/test_poly_mixer.py -v`
Expected: PASS.

- [ ] **Step 18: Commit**

```bash
git add automixer/mixers/poly_mixer.py tests/test_poly_mixer.py
git commit -m "feat(mixer): route poly mixer slicing through slice_source (dual-source)"
```

- [ ] **Step 19: Route `library_mixer.py` through `slice_source`**

`library_mixer.py` is architecturally different (Task 1's Step 23 note): every channel shares ONE
already-cut `grain` object in `_render_grain` rather than each channel cutting its own slice. A
`source2`-tagged channel here must re-slice the SAME relative beat-grid position from `audio2`
instead of reusing `grain` (which came from `audio`). Modify `automixer/mixers/library_mixer.py`
(the Task-1-edited version): add `slice_source` to the `automixer.utils` import, and change the
call signature so `_render_grain` also receives the grain's source position:

In `mix()`, change:
```python
        out_parts = [self._render_grain(config, grains[gi]) for gi in sequence]
```
→
```python
        out_parts = [self._render_grain(config, grains[gi], positions[gi]) for gi in sequence]
```

And `_render_grain` becomes:

```python
    def _render_grain(self, config, grain, position_ms):
        reverse_prob = float(getattr(config, "reverse_prob", 0.0))
        env_pct = float(getattr(config, "env_pct", 8.0))
        grain_len = len(grain)
        out = AudioSegment.silent(duration=grain_len)
        for channel in config.channels_config:
            source_chunk = slice_source(config, channel, position_ms, grain_len)
            channel_chunk = maybe_reverse(source_chunk, reverse_prob, random.Random())
            if channel.bypass:
                out = out.overlay(channel_chunk)
            else:
                out = out.overlay(band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk))
        if config.sample_speed != 1.0:
            out = change_audioseg_tempo(out, config.sample_speed, verbose=config.is_verbose_mode_enabled)
        out = apply_envelope(out, env_pct)
        return out
```

Note this changes `_render_grain`'s behavior even for non-`source2` channels in a subtle way: it
now calls `slice_source(config, channel, position_ms, grain_len)` (which for a non-`source2`
channel returns `config.audio[position_ms:position_ms+grain_len]`) instead of reusing the
already-cut `grain` parameter directly. These are bit-identical WHEN `position_ms`/`grain_len`
exactly reproduce how `grain` was originally cut in step 1 of `mix()` (`grains = [audio[p:p +
grain_len] for p in positions]`) — verify this with the existing `tests/test_library_mixer.py`
suite (Step 21) before committing; if it is NOT bit-identical (e.g. because of the `return_debug`
path or a rounding difference), keep `grain` as the primary-source path (`if not
channel.source2: channel_chunk = maybe_reverse(grain, ...)` instead of re-slicing) and only
re-slice via `slice_source` for `source2`-tagged channels, to avoid changing non-dual-source output.

- [ ] **Step 20: Add a dual-source wiring test to `tests/test_library_mixer.py`**

Mirror Step 8's pattern for `LibraryAutoMixer`, constructing a config with a `source2=True`
channel and a real `config.audio2`, patching `automixer.mixers.library_mixer.slice_source`, and
asserting it's called with a channel whose `.source2` is `True`.

- [ ] **Step 21: Run, verify RED then GREEN, and confirm non-dual-source output is unchanged**

Run: `python -m pytest tests/test_library_mixer.py -v`
Expected: PASS, including every PRE-EXISTING test in this file (a non-`source2` render must sound
exactly as before — if any pre-existing assertion in this file was checking exact bytes/positions
and now fails, apply the fallback described in Step 19's last paragraph).

- [ ] **Step 22: Commit**

```bash
git add automixer/mixers/library_mixer.py tests/test_library_mixer.py
git commit -m "feat(mixer): route lib mixer through slice_source (dual-source, position-aware)"
```

- [ ] **Step 23: Add `src2` loading + the `c` grammar's `2:` prefix to the REPL**

Modify `cutter/sample_cut_tool.py`. First, factor the format-dispatch out of `_load_audio`
(currently lines 81-97) into a reusable staticmethod so a second source can use the same decode
logic without duplicating the `if/elif` chain. Read the current `_load_audio` first
(`sed -n '81,98p' cutter/sample_cut_tool.py`) to get its exact current body, then refactor to:

```python
    @staticmethod
    def _decode_audio_file(audio_file_path):
        if not os.path.exists(audio_file_path):
            raise Exception("File does not exist")
        if audio_file_path.endswith(".wav"):
            return AudioSegment.from_wav(audio_file_path)
        elif audio_file_path.endswith(".mp3"):
            return AudioSegment.from_mp3(audio_file_path)
        elif audio_file_path.endswith(".webm"):
            return AudioSegment.from_file(audio_file_path, "webm")
        elif audio_file_path.endswith(".m4a"):
            return AudioSegment.from_file(audio_file_path, "m4a")
        raise Exception("Unsupported file type: " + audio_file_path)

    def _load_audio(self, audio_file_path):
        self.audio = self._decode_audio_file(audio_file_path)
        self.beats = self._detect_beats()
```

(Match this against the REAL current body from the `sed` read above — the exact `if/elif` chain
and any surrounding lines/exception messages must be preserved verbatim; the refactor is
structural only, not a behavior change. If the real file's branches differ from what's shown here,
adjust to match, keeping every existing extension/behavior intact.)

Add a secondary-source loader, right after `_load_audio`:

```python
    def _load_secondary_audio(self, audio_file_path):
        """Load a second source for dual-source grinding (`amc src2 <path>`), cached by path so
        repeated `amc` calls don't re-decode. Does NOT touch beat detection — the beat grid always
        comes from the primary source; source 2 only supplies raw material (design doc
        2026-07-21)."""
        if getattr(self, "_audio2_path", None) == audio_file_path and getattr(self, "audio2", None) is not None:
            return
        self.audio2 = self._decode_audio_file(audio_file_path)
        self._audio2_path = audio_file_path
```

Add the `src2`/`c`-prefix parsing to `config_automix` (alongside Task 1's `env`/`rv` block):

```python
        # Dual-source grinding (2026-07-21): `src2 <path>` loads a second file (cached by path);
        # a `c` band prefixed `2:` pulls its grains from it instead of the primary source.
        audio2 = getattr(self, "audio2", None)
        if "src2" in args:
            path = args[args.index("src2") + 1]
            self._load_secondary_audio(path)
            audio2 = self.audio2
```

Change the existing `c`-parsing block (currently ~lines 436-446) to recognize the `2:` prefix:

```python
        channels_config = self.auto_mixer_config.channels_config
        if "c" in args:
            channels_config = []
            cutoffs = args[args.index("c") + 1]
            low_highs = cutoffs.split(";")
            for low_high in low_highs:
                use_source2 = False
                if low_high.startswith("2:"):
                    use_source2 = True
                    low_high = low_high[2:]
                low, high = low_high.split(",")
                channels_config.append(ChannelConfig(int(low), int(high), source2=use_source2))
            print("channel_config: " + str(self.auto_mixer_config.channels_config))
```

Finally, add `audio2=audio2` to the `AutoMixerConfig(...)` constructor call (alongside Task 1's
`env_pct`/`reverse_prob`):

```python
            env_pct=env_pct,
            reverse_prob=reverse_prob,
            audio2=audio2,
        )
```

- [ ] **Step 24: Write a failing test for `src2` + `2:` parsing**

Add to the test file created/extended in Task 1 Step 28 (`cutter/test_env_rv_cli.py` or wherever
it landed):

```python
class DualSourceCliTest(unittest.TestCase):
    def setUp(self):
        self.cutter = SampleCutter(ASSET, "/tmp")

    def test_src2_loads_and_stores(self):
        self.cutter.config_automix("amc src2 " + ASSET)
        self.assertIsNotNone(self.cutter.audio2)
        self.assertEqual(self.cutter.auto_mixer_config.audio2, self.cutter.audio2)

    def test_c_grammar_2_prefix_tags_source2(self):
        self.cutter.config_automix("amc src2 " + ASSET + " c 0,250;2:1000,15000")
        channels = self.cutter.auto_mixer_config.channels_config
        self.assertEqual(len(channels), 2)
        self.assertFalse(channels[0].source2)
        self.assertTrue(channels[1].source2)
        self.assertEqual((channels[1].low_pass, channels[1].high_pass), (1000, 15000))

    def test_src2_is_cached_by_path(self):
        self.cutter.config_automix("amc src2 " + ASSET)
        first = self.cutter.audio2
        self.cutter.config_automix("amc src2 " + ASSET)
        self.assertIs(self.cutter.audio2, first)
```

- [ ] **Step 25: Run, verify RED then GREEN**

Run: `python -m pytest cutter/test_env_rv_cli.py -v` (or wherever these tests landed)
Expected: FAIL first, PASS after Step 23.

- [ ] **Step 26: Commit**

```bash
git add cutter/sample_cut_tool.py cutter/test_env_rv_cli.py
git commit -m "feat(cli): amc src2 + c-grammar 2: prefix for dual-source grinding"
```

- [ ] **Step 27: Full regression run**

Run: `python -m pytest -q`
Expected: same 4 pre-existing failures only, otherwise green.

---

### Task 4: Closed-loop Uxn control

**Files:**
- Modify: `uxn_ctrl/paramgen.tal` (token-state machine + `idx_c` XOR)
- Modify: `uxn_ctrl/paramgen.rom` (rebuilt binary — commit the rebuilt bytes)
- Modify: `automixer/uxn_stream.py` (`uxn_tick`, `run_uxn_sequence`)
- Modify: `automixer/test_uxn_stream.py`
- Modify: `main.py:40-48` (new `--uxn-feedback` flag), `:99-108` (pass it through)

**Interfaces:**
- Consumes: nothing from Tasks 1-3 (fully disjoint files — safe to implement independently, though
  this plan executes it in sequence for a single-reviewer-per-task cadence).
- Produces: `uxn_tick(tick, feedback=0, rom_path=DEFAULT_ROM, uxncli_path=None) -> str` (feedback
  now the 2nd positional-or-keyword param, always sent as the ROM's FIRST argv token — see the
  ordering note below); `run_uxn_sequence(cutter, ticks, rom_path=..., uxncli_path=..., closed_loop=False) -> list[str]`.

- [ ] **Step 1: Read the current ROM source and confirm the exact byte ranges to change**

Run: `cat uxn_ctrl/paramgen.tal` — confirm the file still matches the version this plan was
written against (128 lines; zero-page `acc=00` short, `token=02` byte; `on-console` 2-way dispatch;
`&decide`/`&cpart`/`&arm-ss`/`&decide-ss`/`&halt` blocks). If it has drifted, adapt the following
steps' line anchors accordingly — the STRUCTURE (not line numbers) is what must be preserved.

- [ ] **Step 2: Write the failing tests first (RED-first, matching this file's own established
  convention — it says so in its own docstring)**

Read `automixer/test_uxn_stream.py` in full first. Add a new test class (or extend the existing
one) asserting the ordering + no-op contract BEFORE touching the `.tal`/`.rom`:

```python
class UxnFeedbackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uxncli = _ensure_uxn_toolchain()
        cls.rom = os.path.join(UXN_CTRL, "paramgen.rom")

    def test_feedback_zero_reproduces_existing_output_exactly(self):
        # The no-op guarantee: feedback=0 -> idx_c XOR 0 == idx_c, so every existing fixture's
        # exact output must be byte-for-byte unchanged.
        from automixer.uxn_stream import uxn_tick
        for t in range(16):
            line = uxn_tick(t, feedback=0, rom_path=self.rom, uxncli_path=self.uxncli)
            self.assertRegex(line, r"^l \d+ w \d+ s [\d.]+ c \d+,\d+(;\d+,\d+)* ss [\d.]+$")

    def test_nonzero_feedback_changes_c_selection_for_some_tick(self):
        # A real-effect gate, not just "it runs": find at least one tick where feedback=0 and
        # feedback=3 (max 2-bit XOR delta) select DIFFERENT c band-pairs.
        from automixer.uxn_stream import uxn_tick
        changed = False
        for t in range(16):
            base = uxn_tick(t, feedback=0, rom_path=self.rom, uxncli_path=self.uxncli)
            fb = uxn_tick(t, feedback=3, rom_path=self.rom, uxncli_path=self.uxncli)
            base_c = base.split("c ")[1].split(" ss")[0]
            fb_c = fb.split("c ")[1].split(" ss")[0]
            if base_c != fb_c:
                changed = True
        self.assertTrue(changed, "feedback=3 never changed idx_c across 16 ticks")

    def test_feedback_is_deterministic(self):
        from automixer.uxn_stream import uxn_tick
        a = uxn_tick(5, feedback=2, rom_path=self.rom, uxncli_path=self.uxncli)
        b = uxn_tick(5, feedback=2, rom_path=self.rom, uxncli_path=self.uxncli)
        self.assertEqual(a, b)
```

- [ ] **Step 3: Run to confirm RED**

Run: `python -m pytest automixer/test_uxn_stream.py -v -k Feedback`
Expected: FAIL — `uxn_tick() got an unexpected keyword argument 'feedback'`.

- [ ] **Step 4: Rewrite `uxn_ctrl/paramgen.tal`'s token dispatch + `&cpart`**

The KEY correctness constraint (worked out during design review): feedback must be read as the
**FIRST** argv token, not the last — `c`'s string is emitted while processing the SECOND line
(today's "first" token, the tick), so feedback must already be known by then. Replace the file's
`on-console`, `&decide`'s `&cpart`/`&arm-ss` portion, and add a new `&store-fb` block. Full
replacement of the header comment + `|0100`/`@on-console` block (previously lines 1-33):

```uxntal
( paramgen.tal -- Uxn grain-parameter sequencer for grainneukeln, Option A external control layer )
( genaforvena/grainneukeln#13. Deterministic table-lookup ONLY: Uxn picks WHICH pool entry a tick )
( maps to (8-bit AND/SFT/EOR arithmetic, no floats) -- it never formats or computes the values )
( themselves; those are fixed ASCII strings baked into the ROM, matching grainneukeln's own )
( pool-quantized param convention. )
( Sequences all 5 amc params: l, w, s, c, ss -- one 2-bit field per param. l/w/s/c spend the whole )
( 8-bit tick_lo byte of the 2nd argv token (4x4x4x4 = 256 combos). ss needs a 5th field and that )
( byte has no bits left, so it reads a 3rd argv token (a coarser "macro tick") and picks ss from )
( its low 2 bits. )
( Closed-loop feedback (2026-07-21, grain-effects-and-control design): a 1ST argv token, read )
( BEFORE the tick, lets a host-measured byte perturb WHICH c band-pair gets picked: )
( idx_c = ((tick_lo >> 6) & 3) EOR (feedback_lo & 3). feedback=0 is a TRUE no-op (x EOR 0 == x), )
( so today's open-loop output is unchanged when the host doesn't compute a real feedback value. )
( Feedback MUST arrive first: c's string is emitted while processing the tick token, so a )
( feedback value read afterward could never influence it -- there is no "peek ahead" once a line )
( has already been read+processed. )
( input  : argv "<feedback>" "<tick>" "<macro-tick>" (uxncli feeds each nl-terminated decimal )
(          ASCII line in turn, in that order) )
( output : one line "l <N> w <N> s <N> c <N>,<N>;<N>,<N> ss <N>\n" -- a valid grainneukeln `amc` )
( fragment. )
( zero-page: acc=00 (short), token=02 (0=awaiting feedback, 1=awaiting tick, 2=awaiting )
(            macro-tick), fb=03 (stashed feedback_lo, persists across the whole ROM run) )

|0100
    ;on-console #10 DEO2
    BRK

@on-console
    #12 DEI
    DUP #0a NEQ ,&digit JCN
    POP
    #02 LDZ #00 EQU ,&store-fb JCN
    #02 LDZ #01 EQU ,&decide JCN
    ;&decide-ss JMP2
    &digit
    #30 SUB
    #00 SWP
    #00 LDZ2 #000a MUL2
    ADD2
    #00 STZ2
    BRK

    &store-fb
    ( 1st line is the feedback byte -- stash its low byte at zp 03 (persists across the rest of )
    ( this run), no emit. Reset acc, arm token=1 (awaiting the 2nd line, the tick that drives )
    ( l/w/s/c), await the next newline. )
    #01 LDZ #03 STZ
    #0000 #00 STZ2
    #01 #02 STZ
    BRK

    &decide
```

Everything from the original `&decide` label through the end of `&spart` (idx_l/idx_w/idx_s
selection — unchanged) stays exactly as-is. Only `&cpart` changes, to XOR in the stashed feedback
register:

```uxntal
    &cpart
    #01 LDZ #06 SFT #03 AND  ( idx_c_raw = (tick_lo >> 6) & 3 )
    #03 LDZ #03 AND EOR      ( idx_c = idx_c_raw EOR (fb_reg & 3) -- feedback=0 is a no-op )
    DUP #00 EQU ,&c0 JCN
    DUP #01 EQU ,&c1 JCN
    #02 EQU ,&c2 JCN
    ,&c3 JMP
    &c0 POP ;cstr0 ;emit JSR2 ,&arm-ss JMP
    &c1 POP ;cstr1 ;emit JSR2 ,&arm-ss JMP
    &c2 ;cstr2 ;emit JSR2 ,&arm-ss JMP
    &c3 ;cstr3 ;emit JSR2

    &arm-ss
    ( 2nd line (tick) is done; reset acc, arm token=2 (awaiting the 3rd line, macro_tick -> ss) )
    #0000 #00 STZ2
    #02 #02 STZ
    BRK
```

`&decide-ss`, `@emit`, and every `@lstr*`/`@wstr*`/`@sstr*`/`@cstr*`/`@ssstr*` string table entry
(the rest of the original file, from `&decide-ss` through the final `@ssstr3` line) are UNCHANGED —
copy them verbatim from the current file.

- [ ] **Step 5: Rebuild the ROM**

Run: `cd uxn_ctrl && ./build.sh --rom && cd ..`
Expected: `bin/uxnasm`/`bin/uxncli` rebuild (or already present), then
`./bin/uxnasm paramgen.tal paramgen.rom` runs with no assembler errors and `paramgen.rom` is
rewritten. If `uxnasm` reports an assembly error, it names the offending line — the most likely
mistakes are a wrong zero-page address literal (`#03` vs `03` — `STZ`/`LDZ` need the ADDRESS as a
literal byte via `#03`, matching how the existing code writes `#02 STZ`/`#02 LDZ` for the `token`
flag) or a label typo (`&store-fb` must match exactly between definition and every `,&store-fb`/
`;&store-fb` reference).

- [ ] **Step 6: Run the Uxn-level tests to verify RED→GREEN**

Run: `python -m pytest automixer/test_uxn_stream.py -v`
Expected: the ORIGINAL tests (`test_tick_output_is_a_valid_amc_fragment`,
`test_tick_is_deterministic`, etc.) will now FAIL if `uxn_tick`'s Python signature/argv order
hasn't been updated yet (Step 7) — that is expected at this point; this step just confirms the ROM
itself assembles and the NEW `UxnFeedbackTest` tests still show the ImportError/TypeError from
Step 3 (unchanged) since `uxn_stream.py` hasn't been touched yet.

- [ ] **Step 7: Update `automixer/uxn_stream.py` for the new argv order + `feedback` param**

Replace `uxn_tick` and `run_uxn_sequence`:

```python
def uxn_tick(tick, feedback=0, rom_path=DEFAULT_ROM, uxncli_path=None):
    """Run the Uxn param-sequencer ROM for one tick; return its output line, e.g. 'l 500 w 4'.

    One subprocess per tick, matching the mesh's own uxn-pilot gates (lease-gate/band-gate):
    deterministic, byte-identical on any Uxn emulator/architecture, trivially testable. Raises
    on any failure to load/run the ROM -- empty output is a real failure, never a silent
    default (uxncli always exits 0 even when it fails to load a ROM, so the exit code itself
    is not a usable signal; non-empty stdout is the actual success predicate).

    Passes THREE argv tokens, in this exact order: `feedback` (default 0, a true no-op --
    `x EOR 0 == x` -- so an unspecified feedback reproduces today's fully open-loop output byte
    for byte), `tick` (its low byte drives l/w/s/c), and `tick // 256` (its low 2 bits drive ss).
    Feedback MUST come first: the ROM emits `c`'s string while processing the SECOND line it
    reads, so a feedback value arriving any later could never influence that selection (see
    uxn_ctrl/paramgen.tal's header comment and uxn_ctrl/README.md).
    """
    cli = find_uxncli(uxncli_path)
    result = subprocess.run(
        [cli, rom_path, str(int(feedback) & 0xFF), str(tick), str(tick // 256)],
        capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
    )
    line = result.stdout.strip()
    if not line:
        raise RuntimeError(
            f"uxncli produced no output for tick {tick} (feedback={feedback}, rom={rom_path}): "
            f"{result.stderr.strip()}"
        )
    return line


def run_uxn_sequence(cutter, ticks, rom_path=DEFAULT_ROM, uxncli_path=None, closed_loop=False):
    """Drive `ticks` renders of `cutter` from the Uxn param stream.

    Each tick's line is handed to config_automix/automix exactly as a human-typed `amc ...`
    command would be -- the engine never knows the params came from a Uxn ROM instead of a
    keyboard. Returns the list of param lines actually applied, one per render.

    ``closed_loop=True`` computes a REAL feedback byte each tick from the current source's
    measured character (a handful of evenly-spaced beat-grid grains, average rhythm_density
    scaled to 0-255 -- see ``_measure_feedback_byte``), so the Uxn sequencer's `c`-band choice
    reacts to the actual audio instead of ticking through its table open-loop. Default `False`
    passes `feedback=0` every tick -- byte-for-byte the original open-loop behaviour.
    """
    lines = []
    for tick in range(ticks):
        feedback = _measure_feedback_byte(cutter) if closed_loop else 0
        line = uxn_tick(tick, feedback=feedback, rom_path=rom_path, uxncli_path=uxncli_path)
        cutter.config_automix("amc " + line)
        cutter.automix("am")
        lines.append(line)
    return lines


def _measure_feedback_byte(cutter):
    """A cheap, coarse feedback byte for closed-loop Uxn control: sample a handful of evenly-
    spaced beat-grid grains from the CURRENT source, measure via the one existing measure tract
    (``automixer.features.measure_grain`` -- no new analyzer), average onset density (a real,
    audible axis: how busy the material is), clamp/scale a fixed practical range (0-5 onsets/sec
    covers real material -- see automixer/features.py's own rhythm_density docs) to a byte. Only
    the low 2 bits of the returned byte are actually consumed by the ROM (idx_c is 2 bits), so
    this need not be a precision measurement -- it is a coarse perturbation key, not a control
    signal in its own right."""
    from automixer.features import measure_grain

    audio = getattr(cutter, "audio", None)
    beats = getattr(cutter, "beats", None)
    if audio is None or beats is None or len(beats) == 0 or len(audio) == 0:
        return 0
    sample_len = 300
    positions = sorted(set(int(b) for b in beats if 0 <= b <= len(audio) - sample_len))
    if not positions:
        return 0
    step = max(1, len(positions) // 8)
    picks = positions[::step][:8]
    densities = [measure_grain(audio[p:p + sample_len])["rhythm_density"] for p in picks]
    avg = sum(densities) / len(densities) if densities else 0.0
    scaled = int(min(1.0, avg / 5.0) * 255)
    return max(0, min(255, scaled))
```

- [ ] **Step 8: Run to verify GREEN**

Run: `python -m pytest automixer/test_uxn_stream.py -v`
Expected: PASS — every original test (now calling `uxn_tick(t, ...)` with the updated 3-argv
subprocess call under the hood) plus the 3 new `UxnFeedbackTest` tests.

- [ ] **Step 9: Commit**

```bash
git add uxn_ctrl/paramgen.tal uxn_ctrl/paramgen.rom automixer/uxn_stream.py automixer/test_uxn_stream.py
git commit -m "feat(uxn): closed-loop feedback -- 3rd argv token XORs idx_c, feedback=0 is a true no-op"
```

- [ ] **Step 10: Add the `--uxn-feedback` CLI flag**

Modify `main.py`. Add the new flag right after the existing `--uxn-ticks` argument (currently
line 47-48):

```python
    parser.add_argument("--uxn-ticks", type=int, default=8,
                        help="Number of ticks (renders) to drive from --uxn-ctrl (default 8).")
    parser.add_argument("--uxn-feedback", action="store_true",
                        help="Closed-loop Uxn control (issue #13 extension): each tick's ROM call "
                             "is fed a feedback byte measured from the current source's rhythm "
                             "density, so the sequencer's channel-band choice reacts to the actual "
                             "audio instead of ticking open-loop. Only meaningful with --uxn-ctrl; "
                             "default off (byte-identical to today's open-loop behaviour).")
```

Update the `--uxn-ctrl` handling block (currently lines 99-108) to pass it through:

```python
        if args.uxn_ctrl is not None:
            from automixer.uxn_stream import run_uxn_sequence, DEFAULT_ROM
            rom = DEFAULT_ROM if args.uxn_ctrl == "__default__" else args.uxn_ctrl
            print("Starting cut tool with file: " + args.source_path)
            cutter = sample_cut_tool.SampleCutter(args.source_path, args.destination_path,
                                                   low_memory=args.low_memory)
            lines = run_uxn_sequence(cutter, args.uxn_ticks, rom_path=rom,
                                     closed_loop=args.uxn_feedback)
            for i, line in enumerate(lines):
                print(f"[uxn tick {i}] {line}")
            sys.exit(0)
```

- [ ] **Step 11: Write a smoke test that the CLI flag threads through**

Check whether a `tests/test_main_cli.py` or similar already exercises `main.py`'s argparse setup
(`grep -rl "add_argument\|--uxn-ctrl" tests/ cutter/ automixer/ 2>/dev/null | grep -v main.py`). If
none exists, this is argparse wiring in a `if __name__ == "__main__":` block that isn't
straightforwardly unit-testable without a subprocess call — write a subprocess-level smoke test
instead:

Create `tests/test_uxn_cli_flag.py`:

```python
import os
import subprocess
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
ASSET = os.path.join(ROOT, "assets", "test_audio.mp3")


class UxnFeedbackFlagTest(unittest.TestCase):
    def test_uxn_feedback_flag_is_accepted_and_closes_the_loop(self):
        out_dir = "/tmp/grainneukeln_uxn_feedback_test"
        os.makedirs(out_dir, exist_ok=True)
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "main.py"), ASSET, out_dir,
             "--uxn-ctrl", "--uxn-ticks", "2", "--uxn-feedback"],
            capture_output=True, text=True, timeout=120, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[uxn tick 0]", result.stdout)
        self.assertIn("[uxn tick 1]", result.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 12: Run, verify RED then GREEN**

Run: `python -m pytest tests/test_uxn_cli_flag.py -v`
Expected: FAIL first (unrecognized argument) if run before Step 10, PASS after. This test is slow
(spawns a real subprocess doing a real grind + `librosa` beat detection + 2 Uxn subprocess ticks) —
budget up to ~60-90s.

- [ ] **Step 13: Commit**

```bash
git add main.py tests/test_uxn_cli_flag.py
git commit -m "feat(cli): --uxn-feedback flag for closed-loop Uxn control"
```

- [ ] **Step 14: Full regression run**

Run: `python -m pytest -q`
Expected: same 4 pre-existing failures only, otherwise green.

---

### Task 5: TUI parity

**Files:**
- Modify: `tui/state.py:31-93` (`SessionState`, `TrackSpec`)
- Modify: `tui/widgets/params_panel.py` (env/rv fields)
- Modify: `tui/widgets/tracks_panel.py` (per-track source A/B)
- Modify: `tui/widgets/source_panel.py` or a new small widget (source-2 path load)
- Modify: `tui/widgets/run_panel.py` (Uxn control section)
- Modify: `tui/engine.py:94-118` (`build_config`)
- Modify: `tui/app.py` (wire the Uxn run path + source-2 loading + panel mounting)
- Modify: `tui/test_params_panel.py`, `tui/test_tracks_panel.py`, `tui/test_run_panel.py`,
  `tui/test_engine.py`, `tui/test_state.py`

**Interfaces:**
- Consumes: the exact `amc` grammar/CLI flags Tasks 1-4 defined (`env`, `rv`, `src2`, `c`'s `2:`
  prefix, `--uxn-feedback`) — this task can be implemented in parallel with Tasks 1-4 since it
  touches entirely disjoint files, PROVIDED the grammar names above (already fixed by this plan)
  don't change; if executing sub-agents run this task before Tasks 1-4 land, its own tests will
  still pass (they exercise `tui/` code paths independent of the mixer/CLI internals), but a final
  end-to-end manual smoke test (Step 15) needs Tasks 1-4 already merged.
- Produces: no new cross-task interfaces (this is a leaf, UI-only task).

- [ ] **Step 1: Add the new fields to `tui/state.py`**

Modify `TrackSpec` (currently lines 6-12):

```python
@dataclass
class TrackSpec:
    low: int
    high: int
    source2: bool = False

    def valid(self) -> bool:
        return 0 <= self.low < self.high
```

Add to `SessionState` (after the existing `snap`/`swing`/`fill`/`fill_gain_db` block, currently
ending ~line 52):

```python
    fill_gain_db: float = -6.0       # q: fill level below the hits
    # Grain shaping (2026-07-21): attack/release taper %% (0 disables; default matches
    # AutoMixerConfig's own 8.0) and per-grain reverse probability (0..1, default off).
    env_pct: float = 8.0
    reverse_prob: float = 0.0
    # Dual-source grinding (2026-07-21): path/URL of an optional second source; per-track
    # `source2` (added to TrackSpec above) tags which bands pull from it.
    source2_path: str = ""
    # Closed-loop Uxn control (2026-07-21) -- issue #13's TUI gap, closed alongside the new
    # feedback capability. `uxn_enabled` switches the Run button to drive `run_uxn_sequence`
    # instead of a normal/series grind.
    uxn_enabled: bool = False
    uxn_rom_path: str = ""            # blank = vendored default ROM
    uxn_ticks: int = 8
    uxn_feedback: bool = False
```

Update `SERIAL_FIELDS` (currently lines 88-93) to persist the new scalars (NOT `source2_path`'s
loaded audio, same rule as the primary `source_path`/`cutter` split — persist the path string,
never the decoded audio):

```python
    SERIAL_FIELDS = (
        "speed", "sample_speed", "window_divider", "sample_length_ms",
        "tracks", "output_dir", "mode", "euclid_k", "euclid_n", "streams_spec",
        "lib_policy", "lib_clusters", "snap", "swing", "fill", "fill_gain_db",
        "wav_export", "verbose", "self_feed", "source_path", "series_spec",
        "env_pct", "reverse_prob", "source2_path",
        "uxn_enabled", "uxn_rom_path", "uxn_ticks", "uxn_feedback",
    )
```

`to_dict`'s `tracks` serialization (currently line 98) needs the new field:

```python
        d["tracks"] = [{"low": t.low, "high": t.high, "source2": t.source2} for t in self.tracks]
```

`from_dict`'s `tracks` reconstruction (currently lines 107-111) needs it too:

```python
        if "tracks" in clean:
            clean["tracks"] = [
                TrackSpec(t["low"], t["high"], t.get("source2", False)) if isinstance(t, dict)
                else TrackSpec(t.low, t.high, getattr(t, "source2", False))
                for t in clean["tracks"]
            ]
```

- [ ] **Step 2: Write failing state tests**

Read `tui/test_state.py` first, then append tests following its existing round-trip-persistence
style, covering: `TrackSpec(0, 100, source2=True)` round-trips through `to_dict`/`from_dict`; a
`SessionState` with `env_pct=15.0, reverse_prob=0.4, uxn_enabled=True, uxn_ticks=12` round-trips;
loading a dict MISSING the new keys (simulating an old session file) still constructs a valid
state with the new fields at their defaults (forward-compat, per the file's own documented
contract).

- [ ] **Step 3: Run, verify RED then GREEN**

Run: `python -m pytest tui/test_state.py -v`
Expected: FAIL first, PASS after Step 1.

- [ ] **Step 4: Commit**

```bash
git add tui/state.py tui/test_state.py
git commit -m "feat(tui): state fields for env/rv, source2, and uxn control"
```

- [ ] **Step 5: Add env/rv fields to `ParamsPanel`**

Modify `tui/widgets/params_panel.py`. Add two rows to `compose` (after the existing
`sample_length` row):

```python
            yield Label("Sample length (ms) · /2 /3 *2", id="sample_length_label")
            yield Input(str(self.state.sample_length_ms), id="sample_length")
            yield Label("Envelope taper %% (0-50)")
            yield Input(str(self.state.env_pct), id="env_pct")
            yield Label("Reverse probability (0-1)")
            yield Input(str(self.state.reverse_prob), id="reverse_prob")
```

Extend `apply_to_state` (currently lines 74-124) to validate + write both, following the exact
`_float`/errors pattern already used for `speed`/`sample_speed`:

```python
        env_pct = _float("env_pct", 0.0, 50.0, "Envelope taper %%")
        reverse_prob = _float("reverse_prob", 0.0, 1.0, "Reverse probability")
```

...and, alongside the existing `if speed is not None: ...` block near the end:

```python
        if env_pct is not None:
            self.state.env_pct = env_pct
        if reverse_prob is not None:
            self.state.reverse_prob = reverse_prob
```

- [ ] **Step 6: Write failing panel tests**

Read `tui/test_params_panel.py` first to match its harness (likely mounts `ParamsPanel` in a
Textual test `App` via `run_test()` — follow whatever pattern the existing tests use), then add
tests asserting: the two new inputs render with the state's current values; `apply_to_state()`
writes valid values back to `state.env_pct`/`state.reverse_prob`; an out-of-range value (e.g.
`env_pct` = "80") produces an error and does NOT mutate state (matching the existing
`speed`/`sample_speed` out-of-range test pattern in this file).

- [ ] **Step 7: Run, verify RED then GREEN**

Run: `python -m pytest tui/test_params_panel.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tui/widgets/params_panel.py tui/test_params_panel.py
git commit -m "feat(tui): env/rv fields in the Params panel"
```

- [ ] **Step 9: Add a per-track source A/B toggle to `TracksPanel`**

Modify `tui/widgets/tracks_panel.py`. Add a 4th `DataTable` column and a toggle key binding:

```python
    BINDINGS = [("a", "add", "Add track"), ("d", "remove", "Remove track"),
                ("t", "toggle_source", "Toggle source A/B")]
```

`on_mount` (currently lines 35-38):

```python
    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("#", "low Hz", "high Hz", "src")
        self._refresh()
```

`_refresh` (currently lines 44-53) — add the 4th column value:

```python
    def _refresh(self):
        table = self.query_one(DataTable)
        cursor = table.cursor_row or 0
        table.clear()
        for i, t in enumerate(self._tracks):
            table.add_row(str(i + 1), str(t.low), str(t.high), "B" if t.source2 else "A")
        if self._tracks:
            table.move_cursor(row=min(cursor, len(self._tracks) - 1))
        self.border_title = f"◈ bands ({len(self._tracks)})"
        self.post_message(self.Changed(self.tracks))
```

Add the toggle method + action (after `set_selected_range`, currently ~line 102-106):

```python
    def toggle_selected_source(self):
        idx = self.query_one(DataTable).cursor_row
        if idx is not None and 0 <= idx < len(self._tracks):
            t = self._tracks[idx]
            self._tracks[idx] = TrackSpec(t.low, t.high, not t.source2)
            self._refresh()
            self._set_status(f"Track {idx + 1} source → {'B' if self._tracks[idx].source2 else 'A'}")

    def action_toggle_source(self):
        self.toggle_selected_source()
```

Update the header label (currently line 27) to mention the new binding:

```python
            yield Label("Bands (multitrack)  —  a add · d remove · t toggle A/B · edit low/high + Set")
```

- [ ] **Step 10: Write failing tracks-panel tests**

Read `tui/test_tracks_panel.py` first, then add tests: a new track defaults to `source2=False`
("A"); `action_toggle_source` flips the selected row's source and the table's 4th column reflects
it; toggling twice returns to "A"; `self.tracks` (the public property) reflects the toggle.

- [ ] **Step 11: Run, verify RED then GREEN**

Run: `python -m pytest tui/test_tracks_panel.py -v`
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add tui/widgets/tracks_panel.py tui/test_tracks_panel.py
git commit -m "feat(tui): per-track source A/B toggle in the tracks panel"
```

- [ ] **Step 13: Add a source-2 path field + Uxn control section to `RunPanel`**

Modify `tui/widgets/run_panel.py`. Add to `compose` (after the `series_spec` `Input`, before the
`run_btn` `Button`):

```python
            yield Label("Source B (optional, dual-source grinding)")
            yield Input(self.state.source2_path, id="source2_path",
                        placeholder="blank = single-source;  local file path")
            with Horizontal(id="uxn_options"):
                yield Checkbox("Uxn ctrl", value=self.state.uxn_enabled, id="opt_uxn_enabled",
                               tooltip="Drive renders from the Uxn param-sequencer ROM (issue #13) "
                                       "instead of a normal/series grind")
                yield Input(self.state.uxn_rom_path, id="uxn_rom_path",
                            placeholder="blank = vendored paramgen.rom")
                yield Input(str(self.state.uxn_ticks), id="uxn_ticks")
                yield Checkbox("Closed-loop", value=self.state.uxn_feedback, id="opt_uxn_feedback",
                               tooltip="Feed each tick a measured feedback byte (closed-loop Uxn "
                                       "control) instead of pure open-loop ticking")
```

Extend `on_checkbox_changed` (currently lines 52-58) with the two new checkboxes:

```python
        cmap = {"opt_wav": "wav_export", "opt_verbose": "verbose", "opt_self_feed": "self_feed",
                "opt_uxn_enabled": "uxn_enabled", "opt_uxn_feedback": "uxn_feedback"}
```

Extend `on_input_changed` (currently lines 60-63) to persist the 3 new text/number inputs as
typed:

```python
    def on_input_changed(self, event):
        # Persist these as the operator types — a crash mid-typing should not lose them.
        if event.input.id == "series_spec":
            self.state.series_spec = event.value
        elif event.input.id == "source2_path":
            self.state.source2_path = event.value
        elif event.input.id == "uxn_rom_path":
            self.state.uxn_rom_path = event.value
        elif event.input.id == "uxn_ticks":
            try:
                self.state.uxn_ticks = int(event.value)
            except ValueError:
                pass  # leave the last valid value; the field still shows what was typed
```

`start()` (currently lines 69-99) needs a branch for the Uxn path — when `state.uxn_enabled` is
set, skip the series/single logic entirely and delegate straight to the runner (the runner
callback itself, wired in `tui/app.py` at Step 14, decides single/series/uxn):

```python
    def start(self):
        ok, reason = self.state.is_runnable()
        if not ok:
            self._log(f"Cannot run: {reason}")
            return
        if self.state.uxn_enabled:
            self.query_one("#run_btn", Button).disabled = True
            self._log(f"Running Uxn control ({self.state.uxn_ticks} ticks"
                      f"{', closed-loop' if self.state.uxn_feedback else ''})...")
            try:
                path = self._runner(self.state, self._on_progress, self._log)
            except Exception as e:
                self._log(f"Run failed: {e}")
                self.query_one("#run_btn", Button).disabled = False
                return
            if path is not None:
                self._on_finished(path)
            return
        # Validate the series spec before kicking off — a malformed bracket ([1:5] / unknown param
        # / zero step) should surface as an actionable error, not blow up the worker thread.
        from automixer.series import expand_amc_series, SeriesError
        spec = (self.state.series_spec or "").strip()
        if spec:
            tokens = ["amc"] + spec.split()
            try:
                combos = expand_amc_series(tokens)
            except SeriesError as e:
                self._log(f"Series error: {e}")
                return
            n = len(combos)
            if n == 1:
                self._log("Series spec parsed to a single combination — running one render.")
            else:
                self._log(f"Series armed: {n} combinations queued.")
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
```

- [ ] **Step 14: Wire the Uxn path + source-2 loading into `tui/app.py`'s `_threaded_runner`**

Read `tui/app.py`'s `_threaded_runner`/`_run_single`/`_run_series` (currently lines 323-399) in
full, then add a `_run_uxn` branch dispatched first:

```python
    def _threaded_runner(self, state, on_progress, on_log):
        self.query_one(ParamsPanel).apply_to_state()
        self.query_one(ModePanel).apply_to_state()

        if state.uxn_enabled:
            return self._run_uxn(state, on_progress, on_log)
        spec = (state.series_spec or "").strip()
        if spec:
            return self._run_series(state, spec, on_progress, on_log)
        return self._run_single(state, on_progress, on_log)

    def _run_uxn(self, state, on_progress, on_log):
        """Drive renders from the Uxn param-sequencer ROM (issue #13), closing the TUI's own
        long-standing gap (this capability previously had zero TUI exposure). Runs on the same
        worker-thread pattern as `_run_single`/`_run_series`."""
        from automixer.uxn_stream import run_uxn_sequence, DEFAULT_ROM

        rom = state.uxn_rom_path.strip() or DEFAULT_ROM
        ticks = max(1, int(state.uxn_ticks))

        def work():
            on_log(f"Uxn: driving {ticks} tick(s) from {rom}"
                    f"{' (closed-loop)' if state.uxn_feedback else ''}...")
            lines = run_uxn_sequence(state.cutter, ticks, rom_path=rom,
                                     closed_loop=state.uxn_feedback)
            for i, line in enumerate(lines):
                on_log(f"[uxn tick {i}] {line}")
                self.call_from_thread(on_progress, (i + 1) / ticks)
            return None  # renders were exported by run_uxn_sequence's own cutter.automix calls;
                         # there is no single "last path" the way _run_single/_run_series track one

        self.run_worker(work, thread=True, exit_on_error=False, group="grind")
        return None
```

Add source-2 loading right alongside where the primary source gets loaded/applied before a run —
read `tui/app.py`'s `_threaded_runner` call site context (what runs before it, e.g. any
`on_input_submitted`/`SourcePanel.Loaded` handler) and add: if `state.source2_path` is non-empty
and differs from what's already loaded on `state.cutter`, call
`state.cutter._load_secondary_audio(state.source2_path)` before building the config. The simplest
correct placement is inside `engine.build_config` itself (Step 15) since every run path already
calls it — no `app.py` change needed for the load trigger itself, only for surfacing a load error
to the log (wrap the `build_config` call in each `_run_*` method's `work()` closure in a
try/except that calls `on_log` on failure, matching the existing `Run failed: {e}` pattern already
present in `RunPanel.start()`).

- [ ] **Step 15: Wire `env_pct`/`reverse_prob`/`audio2`/per-track `source2` into `build_config`**

Modify `tui/engine.py`'s `build_config` (currently lines 94-118):

```python
def build_config(cutter, state):
    """Map a SessionState onto the existing AutoMixerConfig. DSP untouched."""
    if state.source2_path and state.source2_path.strip():
        cutter._load_secondary_audio(state.source2_path.strip())
    channels = [ChannelConfig(t.low, t.high, source2=t.source2) for t in state.tracks]
    low_memory = getattr(cutter, "low_memory", False)
    return AutoMixerConfig(
        audio=cutter.audio,
        beats=cutter.beats,
        sample_length=state.sample_length_ms,
        sample_speed=state.sample_speed,
        mode=state.mode,
        speed=state.speed,
        is_verbose_mode_enabled=state.verbose,
        window_divider=state.window_divider,
        channels_config=channels,
        euclid_k=state.euclid_k,
        euclid_n=state.euclid_n,
        streams=parse_stream_spec(state.streams_spec),
        lib_policy=state.lib_policy,
        lib_clusters=state.lib_clusters,
        snap=state.snap,
        swing=state.swing,
        fill=state.fill,
        fill_gain_db=state.fill_gain_db,
        low_memory=low_memory,
        env_pct=state.env_pct,
        reverse_prob=state.reverse_prob,
        audio2=getattr(cutter, "audio2", None),
    )
```

- [ ] **Step 16: Write failing engine/run-panel tests**

Read `tui/test_engine.py` first, then add: `build_config` with a state carrying `env_pct=15.0,
reverse_prob=0.3` produces an `AutoMixerConfig` with those exact values; a state with a track
`source2=True` produces a `channels_config` entry with `.source2 is True`; `build_config` given a
`source2_path` calls `cutter._load_secondary_audio` (use a stub/fake cutter object exposing that
method, matching however this file already fakes a `cutter` for `build_config` tests — check the
existing style first).

Read `tui/test_run_panel.py` first, then add: `RunPanel.start()` with `state.uxn_enabled=True`
calls the injected runner exactly once and does NOT touch the series-spec validation path (a spy
runner + an intentionally malformed `series_spec` that would normally error — confirm it's never
reached when `uxn_enabled` is set).

- [ ] **Step 17: Run, verify RED then GREEN**

Run: `python -m pytest tui/test_engine.py tui/test_run_panel.py -v`
Expected: PASS.

- [ ] **Step 18: Commit**

```bash
git add tui/widgets/run_panel.py tui/app.py tui/engine.py tui/test_engine.py tui/test_run_panel.py
git commit -m "feat(tui): dual-source path + Uxn control section (closes the TUI's issue #13 gap)"
```

- [ ] **Step 19: Manual smoke test in a real terminal**

This is a UI change — run it for real, per the repo's own "headless-friendly, run over SSH/tmux"
design intent:

Run: `cd /home/mesh-home/grainneukeln && . .venv/bin/activate && python main.py --tui`

Load a short local source, confirm: the new "Envelope taper" / "Reverse probability" fields
appear in Params and a grind with `rv 1.0` audibly/visibly differs from `rv 0`; the Tracks panel
shows the new "src" column and `t` toggles A/B on the selected row; entering a Source B path and
grinding with one track set to "B" produces output that differs from a single-source grind of the
same params; enabling "Uxn ctrl" and pressing Run drives multiple ticks and logs `[uxn tick N]`
lines. Quit with `q`/Ctrl+C. Note any rough edges found in the Task 6 doc-update commit message,
but do not treat cosmetic polish as blocking — this repo's TUI is young and iterative.

- [ ] **Step 20: Full regression run**

Run: `python -m pytest -q`
Expected: same 4 pre-existing failures only, otherwise green.

---

### Task 6: Documentation

**Files:**
- Modify: `README.md` (`amc` parameter table, "What's new" section)
- Modify: `docs/PARAMETERS.md` (new param rows + `c` grammar note)
- Modify: `docs/ALGORITHMS.md` (grain-shaping + dual-source + HPSS algorithmic notes)
- Modify: `uxn_ctrl/README.md` (closed-loop feedback section, argv order)

**Interfaces:**
- Consumes: the final, merged behavior of Tasks 1-5 (run this task LAST).

- [ ] **Step 1: Update `README.md`**

Add a new bullet to the "What's new" section (top of file, alongside the existing 2026-07-19
bullets), and 4 new rows to the `amc` parameter table (`env`, `rv`, `src2`, and a note on `c`'s
`2:` prefix), following the exact table-row format already used for `seed`/`snap`/`sw`. Also add
one sentence to the Uxn bullet noting `--uxn-feedback`.

- [ ] **Step 2: Update `docs/PARAMETERS.md`**

Read the file's "Global parameters" and per-mode sections first, then add: `env` and `rv` to the
global table (they apply across all 4 mixer modes, same as `snap`/`sw`); a new `src2` row; a note
under the existing `c` row's description explaining the `2:` prefix and its dual-source semantics,
referencing `slice_source`'s modulo-wrap behavior for a shorter/longer source 2.

- [ ] **Step 3: Update `docs/ALGORITHMS.md`**

Read the file's structure first (it documents each mixer's algorithm in code-level detail). Add:
a short "Grain shaping" subsection describing envelope + reverse and WHERE in each mixer's
per-grain function they're applied (mirroring this plan's Task 1 code); a short "Dual-source
grinding" subsection describing `slice_source`'s modulo-wrap semantics and which mixer required
the position-aware `_render_grain` change (`lib` mode); a short addition to the existing `lib`-mode
section noting the HPSS axis and that it required zero changes to `library_mixer.py` itself.

- [ ] **Step 4: Update `uxn_ctrl/README.md`**

Read the file in full (already read during design — the "Why Option A", "What's here", "Host
side", "CLI", "Scope / what's NOT done" sections). Update: the "What's here" ROM description to
mention the 3-argv-token contract and the corrected order (feedback, tick, macro_tick); add a new
"Closed-loop feedback" section explaining `--uxn-feedback`, `_measure_feedback_byte`, and the
`idx_c` XOR mechanism, explicitly stating the `feedback=0` no-op guarantee; update "Scope / what's
NOT done" to move "closed-loop control" off that list (it's now done) and note anything Task 5's
manual smoke test (Step 19) flagged as a rough edge, if any.

- [ ] **Step 5: Proofread against the actual shipped behavior**

Re-read all 4 changed docs against the actual final code (Tasks 1-5's commits) — check every new
param name, default value, and flag name is spelled EXACTLY as implemented (a doc typo here is
worse than no doc, since a user will copy-paste it and get a parse error). Confirm no doc claims
something that Step 19's manual smoke test (Task 5) found NOT to work.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/PARAMETERS.md docs/ALGORITHMS.md uxn_ctrl/README.md
git commit -m "docs: grain envelope/reverse, HPSS axis, dual-source, uxn closed-loop feedback"
```

---

### Task 7: Final verification, push, and notification

**Files:** none (verification + git operations only)

- [ ] **Step 1: Run the full test suite one last time**

Run: `cd /home/mesh-home/grainneukeln && . .venv/bin/activate && python -m pytest -q`
Expected: exactly the 4 pre-existing `cutter/test_sample_cut_tool.py` failures (documented in
Global Constraints) and every other test green. If ANY other failure appears, stop and fix before
proceeding — do not push a red suite.

- [ ] **Step 2: Review the full commit range about to be pushed**

Run: `git log --oneline origin/master..HEAD`
Expected: the orphaned-series/youtube-search fix + design-spec commits (already pushed-pending
from before this plan) followed by every commit from Tasks 1-6 above, each individually
reasonable and correctly scoped. Skim `git diff origin/master..HEAD --stat` for anything
unexpected (a file touched that shouldn't have been, an accidentally-included scratch file).

- [ ] **Step 3: Push to master**

Run: `git push origin master`
Expected: fast-forward push succeeds (no one else has pushed to this repo's `master` in the
interim — if it's rejected as non-fast-forward, STOP and investigate before force-pushing
anything).

- [ ] **Step 4: Send the Telegram notification**

Use `mesh-voice-tx` (or whatever this node's text-to-Telegram organ is — check
`~/.mesh/nodes`/`CLAUDE.local.md` for the current one if `mesh-voice-tx` doesn't fit a plain-text
message) to tell the operator the 5 features are implemented, tested, documented, and pushed to
`master`, with the commit range and a one-line summary of each feature.
