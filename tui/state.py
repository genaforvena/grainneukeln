from dataclasses import dataclass, field


@dataclass
class TrackSpec:
    low: int
    high: int

    def valid(self) -> bool:
        return 0 <= self.low < self.high


@dataclass
class SessionState:
    cutter: object = None
    speed: float = 1.0
    sample_speed: float = 1.0
    window_divider: int = 2
    sample_length_ms: int = 0
    tracks: list = field(default_factory=lambda: [TrackSpec(0, 15000)])
    wav_export: bool = False
    output_dir: str = "output"

    def is_runnable(self) -> tuple[bool, str]:
        if self.cutter is None:
            return False, "No source loaded — enter a file/URL in Source and press Enter"
        if self.sample_length_ms <= 0:
            return False, "Sample length must be > 0"
        if not self.tracks:
            return False, "Add at least one track"
        for i, t in enumerate(self.tracks):
            if not t.valid():
                return False, f"Track {i + 1} range invalid (need 0 <= low < high)"
        return True, ""
