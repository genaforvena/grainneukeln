from dataclasses import dataclass, field


@dataclass
class TrackSpec:
    low: int
    high: int

    def valid(self) -> bool:
        return 0 <= self.low < self.high


MODES = ("rw", "q", "poly", "lib")
LIB_POLICIES = ("similarity", "contrast")


@dataclass
class SessionState:
    cutter: object = None
    speed: float = 1.0
    sample_speed: float = 1.0
    window_divider: int = 2
    sample_length_ms: int = 0
    tracks: list = field(default_factory=lambda: [TrackSpec(0, 15000)])
    output_dir: str = "output"
    # Mixer selection + per-mode effects — parity with the CLI `amc` knobs (issue: the TUI exposed
    # only the 5 mode-neutral params above). Each block below is ignored by the mixers it does not
    # apply to, exactly as in AutoMixerConfig.
    mode: str = "rw"                 # rw | q | poly | lib — picks the mixer
    euclid_k: int = 3                # q: E(k, n) euclidean hits...
    euclid_n: int = 8                # ...over n beat-subdivision slots
    streams_spec: str = ""           # poly: raw `pr` spec, parsed via parse_stream_spec at build time
    lib_policy: str = "similarity"   # lib: similarity | contrast Markov policy over feature clusters
    lib_clusters: int = 6            # lib: cluster count
    snap: bool = False               # placement: pitch-preserving snap-to-slot (composable)
    swing: float = 0.0               # placement: swing % (0/<=50 straight, 66 = 2:1 shuffle)
    fill: bool = True                # q: stitch off-grid remnants into rest slots (else silent rests)
    fill_gain_db: float = -6.0       # q: fill level below the hits
    # Output / render options — parity with the CLI cutter toggles (`set_wav_enabled`,
    # `set_verbose_enabled`, `aminf`). Each is a no-op until toggled, exactly like the CLI.
    wav_export: bool = False         # also write the .wav alongside the .mp3
    verbose: bool = False            # pass is_verbose_mode_enabled through to the mixers
    self_feed: bool = False          # after a grind, reload the exported mp3 as the source (aminf)

    def is_runnable(self) -> tuple[bool, str]:
        if self.cutter is None:
            return False, "No source loaded — enter a file/URL in Source and press Enter"
        if self.sample_length_ms <= 0:
            return False, "Sample length must be > 0"
        if self.mode not in MODES:
            return False, f"Mode must be one of {', '.join(MODES)}"
        if not self.tracks:
            return False, "Add at least one track"
        for i, t in enumerate(self.tracks):
            if not t.valid():
                return False, f"Track {i + 1} range invalid (need 0 <= low < high)"
        return True, ""
