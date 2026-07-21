"""Feature-clustered grain-library mixer (issue #7) — mode ``"lib"``.

Where every other mode picks grains at random (memoryless noise), this one first builds a **library**
of beat-grid grains measured by character (``automixer.features``), clusters them in calibrated feature
space, then **sequences** grains with a Markov policy over the clusters:

- ``similarity`` — stay in / near the current cluster → hypnotic, coherent motion.
- ``contrast`` — jump to a distant cluster → jarring, glitchy motion.

The two policies produce measurably different grain-to-grain feature distances (that's the acceptance
gate — not "both modes run"). Degrades honestly: too few grains to cluster is reported, never faked.
"""
import random

from pydub import AudioSegment
from tqdm import tqdm

from automixer.effects.band_pass import band_pass_filer
from automixer.effects.change_tempo import change_audioseg_tempo
from automixer.effects.grain_shape import maybe_reverse, apply_envelope, grain_shape_params
from automixer.features import measure_grain, calibrate, cluster, next_cluster
from automixer.utils import beat_interval, apply_seed, concat_bit_identical, slice_source


class LibraryAutoMixer:
    def mix(self, config, return_debug=False):
        import numpy as np

        apply_seed(config)
        audio = config.audio
        total_ms = len(audio)
        if total_ms == 0:
            empty = AudioSegment.empty()
            return (empty, {}) if return_debug else empty

        beat_period = beat_interval(config.beats)
        if beat_period <= 0:
            beat_period = config.sample_length if config.sample_length and config.sample_length > 0 else 500.0
        grain_len = int(config.sample_length) if config.sample_length and config.sample_length > 0 else int(beat_period)
        grain_len = max(1, grain_len)

        # 1. Cut candidate grains on the beat grid (one per beat that fits).
        beats = sorted(int(b) for b in config.beats)
        positions = [b for b in beats if 0 <= b <= total_ms - grain_len]
        if len(positions) < 2:
            # honest fallback: tile the grid across the source (still deterministic boundaries)
            positions = list(range(0, max(1, total_ms - grain_len), grain_len))
        grains = [audio[p:p + grain_len] for p in positions]
        n_grains = len(grains)

        # 2. Measure + calibrate against the actual grain set, then cluster.
        feats = [measure_grain(g) for g in tqdm(grains, desc="Measuring grains")]
        norm = calibrate(feats)
        k = int(getattr(config, "lib_clusters", 6))
        degraded = n_grains < max(4, k)
        labels, centroids = cluster(norm, k)
        n_clusters = len(centroids)

        # 3. Sequence via a Markov chain over clusters under the chosen policy.
        policy = str(getattr(config, "lib_policy", "similarity"))
        rng = np.random.default_rng(getattr(config, "seed", None))
        members = {c: [i for i, l in enumerate(labels) if int(l) == c] for c in range(n_clusters)}
        M = max(1, int(round(total_ms / grain_len)))
        cur = int(rng.integers(n_clusters))
        sequence = []
        for _ in range(M):
            pool = members.get(cur) or list(range(n_grains))
            sequence.append(int(rng.choice(pool)))
            cur = next_cluster(cur, centroids, policy, rng)

        # Render the sequenced grains. Collect in a list + concat ONCE at the end (bit-identical
        # to chained ``out += grain``: pydub's __iadd__ falls through to append(crossfade=0), which
        # is byte-concat). Pre-refactor the per-grain append re-copied the running buffer every
        # grain → O(L²) in the rendered length; now O(L).
        out_parts = [self._render_grain(config, grains[gi], positions[gi]) for gi in sequence]
        out = concat_bit_identical(out_parts)

        if degraded:
            print("[lib] honest-degrade: only %d grain(s) for k=%d clusters (%d formed) — clustering "
                  "coarse, sequencing near-random" % (n_grains, k, n_clusters))

        if return_debug:
            return out, {
                "norm": norm, "labels": labels, "centroids": centroids, "sequence": sequence,
                "features": feats, "positions": positions, "degraded": degraded,
                "n_clusters": n_clusters, "n_grains": n_grains, "policy": policy,
            }
        return out

    def _render_grain(self, config, grain, position_ms):
        reverse_prob, env_pct = grain_shape_params(config)
        # Reverse-gating uses a fresh, unseeded ``random.Random()`` here rather than the mixer's
        # own seeded RNG, because grain SELECTION (which grain plays, in what order) is already
        # fully determined by the seeded ``np.random.default_rng(seed)`` local in ``mix()`` before
        # ``_render_grain`` is ever called (see the ``sequence`` list built there) -- reversing is
        # a post-selection cosmetic pass over an already-chosen grain, so it cannot feed back into
        # selection. That means this draw does NOT participate in the seed-reproducibility
        # contract: the same seed can render a given grain forward on one run and reversed on
        # another. That is an honest, known gap (not silently implied to be reproducible) --
        # revisit only if a future task needs ``lib``-mode reversal itself to be seed-stable.
        #
        # Exactly ONE draw per grain (not one per channel/band): every channel below is derived
        # from the same already-selected grain position, differing only by which SOURCE it reads
        # (dual-source grinding, 2026-07-21) and which band-pass gets applied, so the reverse
        # decision is a property of the grain as a whole -- drawing it again per channel would let
        # one band reverse while another stays forward, an incoherent scrambled grain.
        # ``reversed_grain`` captures that one decision (identity check: ``maybe_reverse`` returns
        # the SAME object when it doesn't reverse, a NEW one via ``.reverse()`` when it does) so it
        # can be applied per-channel to whichever bytes ``slice_source`` actually cuts.
        base_chunk = maybe_reverse(grain, reverse_prob, random.Random())
        reversed_grain = base_chunk is not grain
        grain_len = len(grain)
        out = AudioSegment.silent(duration=grain_len)
        for channel in config.channels_config:
            channel_chunk = slice_source(config, channel, position_ms, grain_len)
            if reversed_grain:
                channel_chunk = channel_chunk.reverse()
            if channel.bypass:
                out = out.overlay(channel_chunk)
            else:
                out = out.overlay(band_pass_filer(channel.low_pass, channel.high_pass, channel_chunk))
        if config.sample_speed != 1.0:
            out = change_audioseg_tempo(out, config.sample_speed, verbose=config.is_verbose_mode_enabled)
        out = apply_envelope(out, env_pct)
        return out
