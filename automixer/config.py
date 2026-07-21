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
                 audio2=None):
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
            "Channels Config: " + str(channel_config) + "\n"
