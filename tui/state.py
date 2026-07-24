from dataclasses import dataclass, field, asdict
import json
import os


@dataclass
class TrackSpec:
    """One band the grinder renders. ``bypass`` is the RAW pass-through — no band_pass_filer call.

    Load-bearing default (2026-07-24): the CLI's ``AutoMixerConfig`` resolves an ABSENT ``c`` token
    to ``[ChannelConfig(0, 15000, bypass=True)]``, i.e. an operator who never names a band pays no
    filter cost. The TUI seeded its default track as a REAL 0..15000 filter, so every default TUI
    grind took the slow path the CLI skips — measured on a 20s clip, seed 1: bypass **0.14s** vs
    filtered **3.77s** (27x). A default track is therefore ``bypass=True`` ("raw"); naming a band
    (Set / the ``c`` token / the amc bar) turns the filter ON, exactly as ``amc c lo,hi`` does.
    """

    low: int
    high: int
    source2: bool = False
    bypass: bool = False

    def valid(self) -> bool:
        return 0 <= self.low < self.high

    def label(self) -> str:
        """How the row reads in the tracks table / recipe line."""
        return "raw" if self.bypass else f"{self.low}-{self.high}"


MODES = ("rw", "q", "poly", "lib")
LIB_POLICIES = ("similarity", "contrast")

# Where the live TUI session is checkpointed so a crash never loses what was typed/selected.
# Override via $GRAINNEUKELN_SESSION for tests; default sits in ~/.mesh next to the other mesh state.
SESSION_PATH = os.environ.get(
    "GRAINNEUKELN_SESSION",
    os.path.join(os.path.expanduser("~"), ".mesh", "grainneukeln-session.json"),
)
# Where the params + traceback of a crashed grind are appended — the "what caused it" record.
CRASH_LOG = os.environ.get(
    "GRAINNEUKELN_CRASH_LOG",
    os.path.join(os.path.expanduser("~"), ".mesh", "grainneukeln-crash.log"),
)


@dataclass
class SessionState:
    cutter: object = None
    speed: float = 1.0
    sample_speed: float = 1.0
    window_divider: int = 2
    sample_length_ms: int = 0
    # Default = ONE raw (bypass) band, mirroring the CLI's absent-`c` default. See TrackSpec.
    tracks: list = field(default_factory=lambda: [TrackSpec(0, 15000, bypass=True)])
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
    # Series runs (2026-07-19): sweep one or more amc params across a list/range and render the
    # cartesian product from a single Run. Empty (the default) = single-shot grind — the legacy
    # behaviour. Non-empty = the runner expands the spec and iterates one render per combination,
    # using the params above as the constant base. See automixer/series.py for the grammar.
    series_spec: str = ""
    # Crash-tolerance (operator 2026-07-19: "let it crash, but don't lose session/data; record what
    # caused it"). ``source_path`` is the path/URL last loaded into ``cutter`` — persisted so a
    # crashed session can re-load the SAME source on restart without the operator retyping it.
    # ``cutter`` itself is the in-memory audio (megabytes of PCM) and is never serialized.
    source_path: str = ""
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
    # Reproducibility (2026-07-24): the CLI's `--seed N` / `amc seed N`. None = legacy unseeded
    # behaviour (runs differ). The TUI accepted `--seed` and printed "not wired" — it is wired now,
    # and `automixer.series.apply_amc_to_state` (which already set a bare `seed` attribute for the
    # series sweep `seed [1,2,3]`) finally lands on a field `engine.build_config` reads.
    seed: object = None
    # Aggressive GC for memory-constrained nodes — the CLI's `--low-memory`. Mirrors the flag onto
    # the state so the TUI can toggle it per-run instead of only at launch.
    low_memory: bool = False

    def amc_seed(self):
        """The seed as an int, or None. Tolerates a string typed into the seed field."""
        if self.seed is None or self.seed == "":
            return None
        try:
            return int(self.seed)
        except (TypeError, ValueError):
            return None

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
        if self.uxn_enabled:
            # Validate the Uxn inputs HERE, before a worker thread spawns uxncli and dies on tick 0
            # with a raw FileNotFoundError in the log. A missing ROM / unbuilt emulator is the single
            # most common Uxn-mode failure and it deserves an actionable message, not a traceback.
            if self.uxn_ticks < 1:
                return False, "Uxn ticks must be >= 1"
            rom = (self.uxn_rom_path or "").strip()
            if rom and not os.path.isfile(rom):
                return False, f"Uxn ROM not found: {rom}"
        return True, ""

    # --- crash-tolerant persistence ---
    # The contract: every scalar the operator typed or toggled is restorable from disk. ``cutter``
    # is dropped (it is the loaded audio — reload from ``source_path``). Unknown keys in the JSON
    # are ignored so a future field added to SessionState does not crash an old session file (and
    # vice versa: a removed field in the file is silently absent in the new state).
    SERIAL_FIELDS = (
        "speed", "sample_speed", "window_divider", "sample_length_ms",
        "tracks", "output_dir", "mode", "euclid_k", "euclid_n", "streams_spec",
        "lib_policy", "lib_clusters", "snap", "swing", "fill", "fill_gain_db",
        "wav_export", "verbose", "self_feed", "source_path", "series_spec",
        "env_pct", "reverse_prob", "source2_path",
        "uxn_enabled", "uxn_rom_path", "uxn_ticks", "uxn_feedback",
        "seed", "low_memory",
    )

    def to_dict(self):
        """JSON-safe view of every persisted field. ``cutter`` is excluded."""
        d = asdict(self)
        d["tracks"] = [{"low": t.low, "high": t.high, "source2": t.source2, "bypass": t.bypass}
                       for t in self.tracks]
        d.pop("cutter", None)
        return {k: d[k] for k in self.SERIAL_FIELDS if k in d}

    @classmethod
    def from_dict(cls, d):
        """Build a state from a persisted dict, ignoring unknown keys (forward-compat)."""
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in d.items() if k in known}
        if "tracks" in clean:
            clean["tracks"] = [
                TrackSpec(t["low"], t["high"], t.get("source2", False), t.get("bypass", False))
                if isinstance(t, dict)
                else TrackSpec(t.low, t.high, getattr(t, "source2", False),
                               getattr(t, "bypass", False))
                for t in clean["tracks"]
            ]
        return cls(**clean)

    def save(self, path=SESSION_PATH):
        """Atomically checkpoint to ``path`` so a crash mid-write cannot corrupt the prior session
        (write temp → rename). Best-effort: a write failure must not crash the TUI — return False."""
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = f"{path}.tmp"
            with open(tmp, "w") as f:
                json.dump(self.to_dict(), f, indent=2, sort_keys=True)
            os.replace(tmp, path)
            return True
        except (OSError, TypeError, ValueError):
            return False

    @classmethod
    def load(cls, path=SESSION_PATH):
        """Restore the last checkpoint, or None if absent/unreadable. None (not a default state) so
        the caller can distinguish 'first run' from 'previous state was default'."""
        try:
            with open(path) as f:
                return cls.from_dict(json.load(f))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

