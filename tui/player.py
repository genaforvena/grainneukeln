"""Non-blocking audio playback for the TUI (operator 2026-07-19: 'start/stop/pause/resume/ff/backwards').

The old ``_real_player`` was a blocking ``pydub.playback.play(path)`` — fire-and-forget with NO
control once started. This module gives the OutputPanel a real Player: start/stop/pause/resume/seek,
with wallclock position tracking so the UI can show '0:42 / 3:15' updating live.

Backend: ``ffplay`` (the only player binary on this node — no mpv/vlc/simpleaudio). ffplay is spawned
as a subprocess with ``-nodisp -autoexit -ss <pos>``. Pause/seek/stop are implemented as kill +
re-spawn at the new position — ffplay's interactive keys are unavailable from a subprocess pipe, so
the kill+respawn approximation is the cleanest contract. Wallclock advances ``pos`` while playing;
on pause/seek the captured pos seeds the next spawn's ``-ss``.

``DummyPlayer`` is the headless fallback (no audio device / CI): records every call so tests can
assert on intent without a real ffplay.
"""
import shutil
import subprocess
import time
from typing import Optional


class PlaybackState:
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


SEEK_STEP_SEC = 10.0   # ff/backwards jump — the standard "skip" interval in most players


def _fmt_pos(sec: float) -> str:
    """0:42 / 3:15 style — mm:ss, hours only if the track is over an hour."""
    if sec is None or sec < 0:
        sec = 0.0
    sec = int(sec)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class Player:
    """Abstract playback controller. Every method is non-blocking; position is read via state()."""

    def play(self, path: str, start_at: float = 0.0) -> None:
        raise NotImplementedError

    def pause(self) -> None:
        raise NotImplementedError

    def resume(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def seek(self, delta_sec: float) -> None:
        raise NotImplementedError

    def state(self) -> dict:
        """Returns {state, pos_sec, path}. The OutputPanel reads this each refresh tick to update
        its status line. 'state' is one of PlaybackState.*."""
        raise NotImplementedError


class FFPlayPlayer(Player):
    """Real audio playback via ffplay subprocess.

    Position tracking: ``_pos_sec`` is the position at the start of the current play segment
    (the ``-ss`` we spawned ffplay with); ``_segment_started_monotonic`` is the wallclock at spawn.
    Current position = ``_pos_sec + (monotonic() - _segment_started_monotonic)`` when playing.
    On pause/seek the current position is captured into ``_pos_sec`` and the segment marker cleared;
    the next play re-spawns ffplay at that position.

    Bit-exact resume is not guaranteed — ffplay's ``-ss`` seeks to the nearest keyframe, and the
    wallclock drifts by the seek latency. For a TUI playback controller that is acceptable; the
    operator hears a small jump on pause/resume, not silence or a crash."""

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._path: Optional[str] = None
        self._pos_sec: float = 0.0
        self._segment_started_monotonic: Optional[float] = None
        self._paused: bool = False

    def play(self, path: str, start_at: float = 0.0) -> None:
        self._kill()
        self._path = path
        self._pos_sec = max(0.0, float(start_at))
        self._segment_started_monotonic = time.monotonic()
        self._spawn_ffplay(self._pos_sec)
        self._paused = False

    def pause(self) -> None:
        if self._paused or self._proc is None:
            return
        # Capture current position before killing so resume restarts here.
        self._pos_sec = self._live_pos()
        self._kill()
        self._segment_started_monotonic = None
        self._paused = True

    def resume(self) -> None:
        if not self._paused or self._path is None:
            return
        self._segment_started_monotonic = time.monotonic()
        self._spawn_ffplay(self._pos_sec)
        self._paused = False

    def stop(self) -> None:
        self._kill()
        self._path = None
        self._pos_sec = 0.0
        self._segment_started_monotonic = None
        self._paused = False

    def seek(self, delta_sec: float) -> None:
        if self._path is None:
            return
        new_pos = max(0.0, self._live_pos() + float(delta_sec))
        # Seek = kill + re-spawn at new position (whether playing or paused). The new state is
        # PLAYING — a seek while paused is a resume-from-new-position, matching most players.
        self._kill()
        self._pos_sec = new_pos
        self._segment_started_monotonic = time.monotonic()
        self._spawn_ffplay(self._pos_sec)
        self._paused = False

    def state(self) -> dict:
        # Detect natural exit (track finished) so a stopped ffplay reports STOPPED, not PLAYING.
        if self._proc is not None and self._proc.poll() is not None:
            # Process exited on its own — track ended. Reset to stopped.
            self._proc = None
            self._segment_started_monotonic = None
            self._paused = False
            self._pos_sec = 0.0
            # Keep _path so the UI still shows what was just played (state=stopped distinguishes it).
        if self._paused:
            return {"state": PlaybackState.PAUSED, "pos_sec": self._pos_sec, "path": self._path}
        if self._proc is not None:
            return {"state": PlaybackState.PLAYING, "pos_sec": self._live_pos(), "path": self._path}
        return {"state": PlaybackState.STOPPED, "pos_sec": 0.0, "path": self._path}

    def _live_pos(self) -> float:
        if self._segment_started_monotonic is None:
            return self._pos_sec
        return self._pos_sec + (time.monotonic() - self._segment_started_monotonic)

    def _spawn_ffplay(self, start_at: float) -> None:
        if not shutil.which("ffplay"):
            return   # headless box without ffplay — state() will show STOPPED; UI degrades gracefully
        cmd = ["ffplay", "-nodisp", "-autoexit", "-nostats", "-loglevel", "quiet"]
        if start_at > 0:
            cmd += ["-ss", f"{start_at:.2f}"]
        cmd += [self._path]
        try:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, FileNotFoundError):
            self._proc = None

    def _kill(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        except Exception:
            pass
        self._proc = None


class DummyPlayer(Player):
    """Headless fallback / test stub. Records every call so callers can assert on intent. The
    position advances via wallclock like FFPlayPlayer so the UI's status line moves realistically
    even when nothing is actually playing — useful in tests and on a CI box with no audio device."""

    def __init__(self):
        self._path: Optional[str] = None
        self._pos_sec: float = 0.0
        self._segment_started_monotonic: Optional[float] = None
        self._paused: bool = False
        self.calls = []   # append-only log of every call — tests assert on sequence

    def play(self, path, start_at=0.0):
        self.calls.append(("play", path, start_at))
        self._path = path
        self._pos_sec = max(0.0, float(start_at))
        self._segment_started_monotonic = time.monotonic()
        self._paused = False

    def pause(self):
        self.calls.append(("pause",))
        if not self._paused and self._segment_started_monotonic is not None:
            self._pos_sec = self._live_pos()
            self._segment_started_monotonic = None
            self._paused = True

    def resume(self):
        self.calls.append(("resume",))
        if self._paused:
            self._segment_started_monotonic = time.monotonic()
            self._paused = False

    def stop(self):
        self.calls.append(("stop",))
        self._path = None
        self._pos_sec = 0.0
        self._segment_started_monotonic = None
        self._paused = False

    def seek(self, delta_sec):
        self.calls.append(("seek", delta_sec))
        if self._path is None:
            return
        new_pos = max(0.0, self._live_pos() + float(delta_sec))
        self._pos_sec = new_pos
        self._segment_started_monotonic = time.monotonic()
        self._paused = False

    def state(self):
        if self._paused:
            return {"state": PlaybackState.PAUSED, "pos_sec": self._pos_sec, "path": self._path}
        if self._path is not None and self._segment_started_monotonic is not None:
            return {"state": PlaybackState.PLAYING, "pos_sec": self._live_pos(), "path": self._path}
        return {"state": PlaybackState.STOPPED, "pos_sec": 0.0, "path": self._path}

    def _live_pos(self):
        if self._segment_started_monotonic is None:
            return self._pos_sec
        return self._pos_sec + (time.monotonic() - self._segment_started_monotonic)


def make_player() -> Player:
    """Pick the best player for this node. FFPlayPlayer if ffplay is on PATH, else DummyPlayer
    (so a headless box with no audio device does not crash on first play — the UI shows the status
    line advancing, indicating intent even when silent)."""
    if shutil.which("ffplay"):
        return FFPlayPlayer()
    return DummyPlayer()
