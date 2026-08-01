from automixer.mixers.default_mixer import RandomWindowAutoMixer
from automixer.mixers.quantized_mixer import QuantizedAutoMixer
from automixer.mixers.poly_mixer import PolyphonicAutoMixer
from automixer.mixers.library_mixer import LibraryAutoMixer


class ChannelConfig:
    """One band-pass channel. With ``bypass=True`` the channel is a RAW pass-through — no
    ``band_pass_filer`` call — used as the default so a plain ``amc …`` (no ``c`` arg) skips the
    ~87%-of-wall-clock BPF cost. Explicit ``c low,high`` in the amc string still constructs
    non-bypass channels (the slow, filtered path), so the operator opts INTO BPF by naming bands
    and opts OUT by omitting the ``c`` arg. The two paths are audibly distinct (filtered vs raw)
    but each is internally bit-identical run-to-run under the same seed. With ``source2=True``
    (the ``2:`` band prefix in ``c``) the band pulls its grains from ``config.audio2`` instead of
    the primary source — same beat grid, different raw material."""

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

    def __str__(self):
        src = " [src2]" if self.source2 else ""
        if self.bypass:
            return "bypass" + src
        return "Low: " + str(self.low_pass) + "; High: " + str(self.high_pass) + src


def parse_stream_spec(spec):
    """Parse a poly ("poly") `pr` stream spec into the list-of-dicts `streams` form.

    Grammar (identical to the CLI `amc pr` argument): segments separated by ";", each
    ``ratio[@length][:low-high]`` — e.g. ``4:1-2000;3:6000-15000`` is two banded streams
    (ratios 4 & 3), ``3;2`` is two full-band streams. Empty/whitespace -> None (mixer default).
    This is the SINGLE parser for the spec; both the CLI and the TUI call it so the two entry
    points can never drift.
    """
    spec = (spec or "").strip()
    if not spec:
        return None
    streams = []
    for seg in spec.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        stream = {}
        head, _, band = seg.partition(":")
        ratio_part, _, length_part = head.partition("@")
        stream["ratio"] = int(ratio_part)
        if length_part:
            stream["length"] = float(length_part)
        if band:
            low, high = band.split("-")
            stream["channels"] = [ChannelConfig(int(low), int(high))]
        streams.append(stream)
    return streams or None


class AutoMixerConfig:
    modes = {
        "rw": RandomWindowAutoMixer,
        "q": QuantizedAutoMixer,
        "poly": PolyphonicAutoMixer,
        "lib": LibraryAutoMixer,
    }

    def __init__(self,
                 audio,
                 beats,
                 sample_length,
                 sample_speed=1.0,
                 mode="rw",
                 speed=1.0,
                 is_verbose_mode_enabled=False,
                 window_divider=2,
                 channels_config=None,
                 euclid_k=3,
                 euclid_n=8,
                 streams=None,
                 lib_policy="similarity",
                 lib_clusters=6,
                 snap=False,
                 swing=0,
                 groove_template=None,
                 fill=True,
                 fill_gain_db=-6.0,
                 seed=None,
                 low_memory=False,
                 env_pct=8.0,
                 reverse_prob=0.0,
                 audio2=None,
                 pattern=None,
                 cycle_beats=1.0,
                 accents=None,
                 pattern_label=None,
                 target_ms=None):
        if mode not in self.modes:
            print("Invalid mode. Defaulting to random.")
            print("Valid modes: " + str(self.modes.keys()))
            mode = "rw"
        self.mode = mode
        self.audio = audio
        # Dual-source grinding (2026-07-21): the SECOND source's raw audio, or None (default —
        # single-source, today's behaviour). Only channels with ``source2=True`` ever read this;
        # the beat grid always comes from the primary source regardless.
        self.audio2 = audio2
        self.beats = beats
        self.sample_speed = sample_speed
        self.mixer = self.modes[mode]
        self.speed = speed
        self.sample_length = sample_length
        self.is_verbose_mode_enabled = is_verbose_mode_enabled
        self.window_divider = window_divider
        # Default = ONE bypass (raw pass-through) channel — skips band_pass_filer entirely, the
        # ~87%-of-wall-clock win (cProfile, 2026-07-19). Explicit ``c low,high`` in the amc string
        # constructs non-bypass channels and opts back into the filtered path. ``None`` here is the
        # sentinel for "user did not specify"; resolved to ``[ChannelConfig(0, 15000, bypass=True)]``
        # below so downstream code sees a non-empty list (the mixers' per-channel loop iterates it).
        if channels_config is None:
            channels_config = [ChannelConfig(0, 15000, bypass=True)]
        self.channels_config = channels_config
        # Quantized ("q") mixer: euclidean pattern E(euclid_k, euclid_n) — k hits over n beat
        # subdivision slots. Ignored by the rw mixer.
        self.euclid_k = euclid_k
        self.euclid_n = euclid_n
        # Cyclic pattern engine (2026-07-24, `amc pat/cyc/rot/acc`): an explicit 0/1 slot list
        # REPLACES the euclidean generator (`pattern`), `cycle_beats` is how many beats one cycle
        # of it spans (the euclidean grid hardcoded 1 — right for a tresillo, wrong for a 16-pulse
        # clave), and `accents` is a per-slot gain map in dB carrying the cycle's accent structure
        # (a teental theka strikes all 16 matras; the khali at 9 is what makes it teental).
        # pattern=None + cycle_beats=1.0 + accents=None is exactly today's E(k,n) behaviour.
        # Resolved by `automixer.iterators.patterns.resolve_pattern` — the one parser the CLI and
        # the TUI share.
        self.pattern = list(pattern) if pattern else None
        self.cycle_beats = float(cycle_beats) if cycle_beats else 1.0
        self.accents = list(accents) if accents else None
        # What to CALL this cycle in the render's filename. Without it a `pat clave32` render is
        # saved as `k3_n8` — the euclidean defaults the mixer never used — and the corpus loses
        # any record of which timeline actually produced the audio.
        self.pattern_label = pattern_label
        # Poly ("poly") mixer: list of {ratio, length?, channels?} stream dicts. None -> a default
        # 3-against-4. Ignored by the other mixers.
        self.streams = streams
        # Library ("lib") mixer: Markov policy over feature clusters ("similarity"/"contrast") and the
        # cluster count. Ignored by the other mixers.
        self.lib_policy = lib_policy
        self.lib_clusters = lib_clusters
        # Placement effects (issue #8), composable across modes: pitch-preserving snap-to-slot, and
        # swing % / groove-template micro-timing offsets. snap=False, swing=0, template=None are no-ops.
        self.snap = snap
        self.swing = swing
        self.groove_template = groove_template
        # Quantized ("q") mixer gap-fill (operator 2026-07-18): stitch off-grid remnants into the
        # euclidean REST slots instead of leaving silence; fills sit `fill_gain_db` below the hits so
        # the groove still reads. fill=False restores the pure-grid (silent-rest) behaviour.
        self.fill = fill
        self.fill_gain_db = fill_gain_db
        self.seed = seed
        self.low_memory = low_memory
        # Grain shaping (2026-07-21): attack/release taper (% of grain length, always-on unless
        # explicitly zeroed -- a hard-cut boundary is a defect, not a creative choice) and
        # per-grain reverse probability (0..1, default off -- today's character unchanged).
        self.env_pct = float(env_pct)
        self.reverse_prob = float(reverse_prob)
        # Output length bound in ms, or None = unbounded (today's behaviour, unchanged).
        #
        # The rw mixer is the ONLY mixer with no length bound: q/poly/lib all canvas at ``total_ms``
        # (the source length), while rw emits ``n_windows × calculate_step(beats)`` and stops when
        # it runs out of windows. ``calculate_step`` is ``mean(beat POSITIONS)/4`` — roughly an
        # EIGHTH OF THE TRACK LENGTH, not any beat quantity (``beat_interval``'s docstring has said
        # so since 2026-07-24; the consequence for rw's output length was never drawn). Windows step
        # by one beat, so the render is ``n_beats × duration/8`` — QUADRATIC in source duration.
        #
        # Measured on the operator's 254.9s source (2026-08-01): 408 beats, real beat period 592ms,
        # calculate_step 31285ms. w=5 -> 328 windows × 31.3s = 10261s of audio. A 2.9-HOUR render
        # for a 4-minute source, 40.3x. It never finished: ~1.9GB of int16 in the join, ×4 through
        # the float64 export path, cgroup-OOM-killed (rc=137) at a 9GB ceiling and again at 16GB.
        # No memory budget fixes a quadratic — 01/02/03 died the same way at both ceilings.
        # Short sources hid it (the sound reflex caps its feed ~65s, where 8x is merely "long").
        #
        # Set it and rw stops at the bound, trimming the last window exactly. Left None, nothing
        # changes for any existing consumer — this does NOT silently re-cut every rw grind in the
        # mesh, whose gates are tuned around today's lengths. Fixing ``calculate_step`` itself is
        # the real repair and belongs to the sound lane, which owns that blast radius.
        self.target_ms = int(target_ms) if target_ms else None

    def __str__(self):
        channel_config = [str(channel) for channel in self.channels_config]
        return "Audio: " + str(len(self.audio)) + "\n" + \
            "Beats: " + str(len(self.beats)) + "\n" + \
            "Mixer: " + str(self.mixer) + "\n" + \
            "Mode: " + str(self.mode) + "\n" + \
            "Speed: " + str(self.speed) + "\n" + \
            "Sample Length: " + str(self.sample_length) + "\n" + \
            "Sample Speed: " + str(self.sample_speed) + "\n" + \
            "Verbose Mode Enabled: " + str(self.is_verbose_mode_enabled) + "\n" + \
            "Window Divider: " + str(self.window_divider) + "\n" + \
            "Channels Config: " + str(channel_config) + "\n" + \
            "Target Length: " + (str(self.target_ms) + "ms" if self.target_ms else "unbounded") + "\n" + \
            "Low Memory: " + str(self.low_memory) + "\n"
