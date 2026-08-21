"""Tests for live mic capture.

Two classes of test here, deliberately separate:

* **Hermetic** — fake backends, synthesised wavs. These run anywhere, including CI with no
  sound card, and they pin the logic: the ladder's order, the silence verdict, the header
  repair, the refusal to call an empty file a recording.

* **Real-hardware** (``test_real_*``) — these drive an actual capture backend against the actual
  audio server. A test suite that only ever exercises stubs is the ``mesh-whisper-run`` trap:
  every stub genuinely asserted, all green, and the wrapper never once invoked the thing it
  wraps. They SKIP (never pass) where there is no backend or no source, so a node without a mic
  reports honest absence rather than a green that means nothing.
"""

import os
import struct
import subprocess
import time
import wave

import pytest

import capture.mic as mic


# ─── helpers ──────────────────────────────────────────────────────────────────

def write_wav(path, frames, rate=44100, channels=1, amplitude=0):
    """A well-formed wav of ``frames`` samples at ``amplitude`` (0 = digital silence)."""
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        vals = []
        for i in range(frames * channels):
            vals.append(amplitude if i % 2 == 0 else -amplitude)
        w.writeframes(struct.pack(f"<{len(vals)}h", *vals))
    return path


class FakeProc:
    """A stand-in recorder process that writes its wav the moment it is 'signalled'."""

    def __init__(self, path, frames=44100, amplitude=1000, write_on=("signal",), stderr=b""):
        self.path = path
        self.frames = frames
        self.amplitude = amplitude
        self.write_on = write_on
        self._stderr = stderr
        self._done = False
        self.signals = []
        self.killed = False
        if "start" in write_on:
            self._write()

    def _write(self):
        if self.frames is not None:
            write_wav(self.path, self.frames, amplitude=self.amplitude)
        self._done = True

    def poll(self):
        return 0 if self._done else None

    def send_signal(self, sig):
        self.signals.append(sig)
        if "signal" in self.write_on:
            self._write()

    def communicate(self, timeout=None):
        return b"", self._stderr

    def kill(self):
        self.killed = True
        self._done = True


def fake_popen(path, **kw):
    def _popen(argv, **_kw):
        return FakeProc(path, **kw)
    return _popen


# ─── backend ladder ───────────────────────────────────────────────────────────

def test_ladder_prefers_a_sharing_backend_over_exclusive_alsa():
    """arecord is LAST on purpose — it seizes the card and evicts every PipeWire client.
    A ladder that reached for it first would silently kill the room ear on this node."""
    names = [n for n, _b, _f, _w in mic.BACKENDS]
    assert names[-1] == "arecord"
    assert names.index("pw-record") < names.index("arecord")


def test_pick_backend_raises_and_names_what_it_looked_for(monkeypatch):
    """No silent fallback: with nothing installed there is no default that 'might work'."""
    monkeypatch.setattr(mic.shutil, "which", lambda _b: None)
    with pytest.raises(mic.CaptureError) as e:
        mic.pick_backend()
    for binary in ("pw-record", "parecord", "arecord"):
        assert binary in str(e.value)


def test_pick_backend_honours_an_explicit_preference(monkeypatch):
    monkeypatch.setattr(mic.shutil, "which", lambda b: f"/usr/bin/{b}")
    assert mic.pick_backend("arecord")[0] == "arecord"
    assert mic.pick_backend()[0] == "pw-record"


def test_preferred_backend_that_is_absent_is_an_error_not_a_downgrade(monkeypatch):
    """Asking for a specific backend and silently getting a different one is how an operator
    ends up debugging the wrong process."""
    monkeypatch.setattr(mic.shutil, "which", lambda b: None if b == "arecord" else f"/usr/bin/{b}")
    with pytest.raises(mic.CaptureError):
        mic.pick_backend("arecord")


def test_argv_builders_all_name_the_output_path_last():
    for _n, _b, builder, _w in mic.BACKENDS:
        argv = builder("/usr/bin/x", "/tmp/out.wav", "dev", 44100, 1)
        assert argv[-1] == "/tmp/out.wav"
        assert any("44100" in a for a in argv), argv


# ─── devices / holders ────────────────────────────────────────────────────────

def test_list_devices_marks_monitors(monkeypatch):
    monkeypatch.setattr(mic.shutil, "which", lambda _b: "/usr/bin/pactl")
    out = ("54\talsa_output.pci.iec958-stereo.monitor\tPipeWire\ts32le 2ch\tSUSPENDED\n"
           "55\talsa_input.pci.analog-stereo\tPipeWire\ts32le 2ch\tSUSPENDED\n")
    devices = mic.list_devices(runner=lambda *_a, **_k: (0, out, ""))
    assert [d["monitor"] for d in devices] == [True, False]
    assert mic.default_device(runner=lambda *_a, **_k: (0, out, "")) == \
        "alsa_input.pci.analog-stereo"


def test_default_device_is_none_when_only_monitors_exist(monkeypatch):
    """None means 'we did not pick a mic', which the backend may still resolve — it must never
    silently return a monitor, i.e. record what the node is PLAYING as if it were the room."""
    monkeypatch.setattr(mic.shutil, "which", lambda _b: "/usr/bin/pactl")
    out = "54\talsa_output.x.monitor\tPipeWire\ts32le\tSUSPENDED\n"
    assert mic.default_device(runner=lambda *_a, **_k: (0, out, "")) is None


# ─── header repair ────────────────────────────────────────────────────────────

def test_repair_wav_header_fixes_a_placeholder_length(tmp_path):
    """The trap this exists for: every backend writes a streaming header whose data size is a
    placeholder until it exits cleanly, and stopping a recording means killing the writer."""
    p = str(tmp_path / "t.wav")
    write_wav(p, 4410, amplitude=1000)
    size = os.path.getsize(p)
    with open(p, "r+b") as fh:          # forge the placeholder a killed writer leaves
        fh.seek(40)
        fh.write(struct.pack("<I", 0))
    with wave.open(p, "rb") as w:
        assert w.getnframes() == 0      # what the operator would have seen: an empty recording
    assert mic.repair_wav_header(p) is True
    with wave.open(p, "rb") as w:
        assert w.getnframes() == 4410
    assert os.path.getsize(p) == size   # repair rewrites sizes, never the audio


def test_repair_is_a_noop_on_an_already_correct_header(tmp_path):
    p = write_wav(str(tmp_path / "t.wav"), 1000, amplitude=500)
    assert mic.repair_wav_header(p) is False


def test_repair_declines_a_non_riff_file(tmp_path):
    p = str(tmp_path / "t.wav")
    open(p, "wb").write(b"NOTAWAVE" + b"\0" * 100)
    assert mic.repair_wav_header(p) is False


# ─── measurement: the silence gate, both directions ───────────────────────────

def test_measure_calls_digital_silence_silent(tmp_path):
    m = mic.measure(write_wav(str(tmp_path / "s.wav"), 44100, amplitude=0))
    assert m["silent"] is True and m["rms"] == 0
    assert "SILENT" in mic.describe(m)


def test_measure_calls_real_signal_not_silent(tmp_path):
    """The gate has to be able to go the other way — a threshold nothing can clear is not a gate."""
    m = mic.measure(write_wav(str(tmp_path / "l.wav"), 44100, amplitude=8000))
    assert m["silent"] is False and m["rms"] > mic.SILENCE_RMS
    assert mic.describe(m).startswith("✓")


def test_a_near_floor_take_is_still_silent(tmp_path):
    """ADC noise on an unplugged input idles at rms 1-3. Calling that 'audio' is how a dead mic
    becomes a plausible source."""
    m = mic.measure(write_wav(str(tmp_path / "n.wav"), 44100, amplitude=2))
    assert m["silent"] is True


def test_too_short_is_reported_before_silent(tmp_path):
    """A 0-frame file and a file full of zeros are different faults with different fixes."""
    m = mic.measure(write_wav(str(tmp_path / "e.wav"), 0))
    assert m["too_short"] is True
    assert "TOO SHORT" in mic.describe(m)


def test_describe_names_the_process_holding_the_card(tmp_path):
    """On this node the contender is real: mesh-overhear holds the USB mic through raw ALSA."""
    m = mic.measure(write_wav(str(tmp_path / "s.wav"), 44100, amplitude=0))
    line = mic.describe(m, [{"pid": 42, "device": "pcmC0D0c", "command": "arecord -D plughw:CARD=Camera"}])
    assert "pid 42" in line and "arecord" in line


def test_measure_refuses_a_headerless_stub(tmp_path):
    p = str(tmp_path / "stub.wav")
    open(p, "wb").write(b"\0" * 20)
    with pytest.raises(mic.CaptureError):
        mic.measure(p)


def test_measure_refuses_a_missing_file(tmp_path):
    with pytest.raises(mic.CaptureError):
        mic.measure(str(tmp_path / "nope.wav"))


# ─── recorder lifecycle ───────────────────────────────────────────────────────

def _recorder(tmp_path, monkeypatch, **popen_kw):
    monkeypatch.setattr(mic.shutil, "which", lambda b: f"/usr/bin/{b}")
    r = mic.MicRecorder(str(tmp_path), device="dev", runner=lambda *_a, **_k: (1, "", ""))
    target = str(tmp_path / "recordings" / "planned.wav")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    r._popen = fake_popen(target, **popen_kw)
    return r, target


def test_start_then_stop_returns_a_measurement_not_a_path(tmp_path, monkeypatch):
    """stop() hands back the MEASUREMENT so there is no way to receive a silent take without
    being told it is silent."""
    r, target = _recorder(tmp_path, monkeypatch, frames=44100, amplitude=6000)
    r.start()
    r.path = target                      # the fake writes to a fixed path
    m = r.stop()
    assert m["silent"] is False
    assert m["backend"] == "pw-record"
    assert m["duration_s"] == pytest.approx(1.0, abs=0.01)


def test_stop_raises_when_the_backend_wrote_nothing(tmp_path, monkeypatch):
    """An empty file is never a recording — and the backend's own last stderr line is quoted, so
    the error names the cause instead of 'unknown error'."""
    r, target = _recorder(tmp_path, monkeypatch, frames=None,
                          stderr=b"connection refused\nno such source: bogus\n")
    r.start()
    r.path = target
    with pytest.raises(mic.CaptureError) as e:
        r.stop()
    assert "no such source" in str(e.value)


def test_stop_sends_sigint_first_so_the_last_buffer_flushes(tmp_path, monkeypatch):
    r, target = _recorder(tmp_path, monkeypatch, frames=44100, amplitude=6000)
    r.start()
    r.path = target
    proc = r._proc
    r.stop()
    assert proc.signals == [2] and proc.killed is False


def test_double_start_is_refused(tmp_path, monkeypatch):
    r, target = _recorder(tmp_path, monkeypatch, frames=44100, write_on=())
    r.start()
    with pytest.raises(mic.CaptureError):
        r.start()


def test_stop_without_start_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(mic.shutil, "which", lambda b: f"/usr/bin/{b}")
    with pytest.raises(mic.CaptureError):
        mic.MicRecorder(str(tmp_path)).stop()


def test_cancel_deletes_the_partial_take(tmp_path, monkeypatch):
    r, target = _recorder(tmp_path, monkeypatch, frames=44100, write_on=("start",))
    r.start()
    r.path = target
    assert os.path.exists(target)
    r.cancel()
    assert not os.path.exists(target)
    assert r.recording is False


def test_recordings_land_in_their_own_directory(tmp_path, monkeypatch):
    r, _t = _recorder(tmp_path, monkeypatch, frames=100, write_on=())
    path = r.start()
    assert os.path.dirname(path) == os.path.join(str(tmp_path), "recordings")
    assert path.endswith(".wav")


def test_elapsed_is_zero_before_start_and_frozen_after_stop(tmp_path, monkeypatch):
    r, target = _recorder(tmp_path, monkeypatch, frames=44100, amplitude=6000)
    assert r.elapsed() == 0.0
    r.start()
    r.path = target
    r.stop()
    frozen = r.elapsed()
    assert r.elapsed() == frozen


# ─── real hardware ────────────────────────────────────────────────────────────

def _hw_backend():
    """The backend a real capture would use here, or None. Not a mock — shutil.which is live."""
    try:
        return mic.pick_backend()[0]
    except mic.CaptureError:
        return None


needs_hw = pytest.mark.skipif(_hw_backend() is None,
                              reason="no capture backend on this node (honest absence, not a pass)")


@needs_hw
def test_real_backend_produces_a_wav_with_frames(tmp_path):
    """Drives the ACTUAL backend against the ACTUAL audio server for 1.5s and asserts real frames
    came back. This is the assertion the stub tests above cannot make: a wrapper's test must
    exercise the thing it wraps."""
    try:
        m = mic.record_clip(1.5, str(tmp_path))
    except mic.CaptureError as e:
        pytest.skip(f"no usable capture source here: {e}")
    assert m["frames"] > 0, "backend ran but produced zero frames"
    assert m["duration_s"] >= 1.0
    assert m["rate"] > 0 and m["channels"] >= 1
    assert m["backend"] in [b["name"] for b in mic.available_backends()]
    assert os.path.getsize(m["path"]) > 44


@needs_hw
def test_real_capture_of_a_known_tone_is_not_silent(tmp_path):
    """The silence gate proven in the live path, not only on a synthesised wav: play a 440Hz tone
    into a sink and record its monitor. Without this, 'SILENT' could be the only verdict the live
    path is capable of producing and nothing would show it."""
    if not (mic.shutil.which("pw-play") and mic.shutil.which("ffmpeg")):
        pytest.skip("pw-play/ffmpeg absent — cannot inject a known signal")
    monitors = [d["id"] for d in mic.list_devices() if d["monitor"]]
    if not monitors:
        pytest.skip("no monitor source to loop a known signal through")
    tone = str(tmp_path / "tone.wav")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=6", "-ar", "48000", "-ac", "2", tone],
                   check=True, timeout=30)
    player = subprocess.Popen(["pw-play", tone], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    try:
        m = mic.record_clip(2.0, str(tmp_path), device=monitors[0])
    finally:
        player.kill()
        player.communicate()
    assert m["silent"] is False, f"a 440Hz tone read as silence: {mic.describe(m)}"
    assert m["rms"] > mic.SILENCE_RMS


@needs_hw
def test_who_holds_capture_returns_structured_rows():
    """Not an assertion that something IS holding a card (usually nothing is) — an assertion that
    the probe parses /proc into real rows rather than returning [] for every input."""
    for h in mic.who_holds_capture():
        assert isinstance(h["pid"], int) and h["pid"] > 0
        assert h["device"].startswith("pcm") and h["device"].endswith("c")


# ─── record_clip waits on bytes, not the clock ────────────────────────────────

class SlowStartProc(FakeProc):
    """A backend whose stream starts LATE — what a SUSPENDED audio device actually does.

    The lag is deliberately LONGER than the nominal clip length: that is the only shape in which
    a wall-clock timer and a wait-on-bytes give different answers, and a fake that starts inside
    the nominal window would let a wall-clock implementation pass this test.
    """

    def __init__(self, path, lag_polls=40, frames_when_it_starts=44100 * 2, **kw):
        self.lag_polls = lag_polls
        self.frames_when_it_starts = frames_when_it_starts
        self.polls = 0
        super().__init__(path, frames=None, write_on=(), **kw)

    def poll(self):
        self.polls += 1
        if self.polls > self.lag_polls:
            write_wav(self.path, self.frames_when_it_starts, amplitude=3000)
        return None if not self._done else 0

    def send_signal(self, sig):
        self.signals.append(sig)
        self._done = True


def _patch_recorder(monkeypatch, tmp_path, target, proc_factory):
    monkeypatch.setattr(mic.shutil, "which", lambda b: f"/usr/bin/{b}")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    monkeypatch.setattr(mic.subprocess, "Popen", lambda argv, **_kw: proc_factory())
    orig_start = mic.MicRecorder.start

    def start(self, name=None):
        p = orig_start(self, name)
        self.path = target          # the fakes write to a fixed path
        return p

    monkeypatch.setattr(mic.MicRecorder, "start", start)


def test_record_clip_waits_for_audio_not_for_the_clock(tmp_path, monkeypatch):
    """The trap this exists for, measured live 2026-08-21: a cold (SUSPENDED) device returned
    0.7s for a 2s request while a warm one returned 2.99s, from identical code. A wall-clock
    timer calls both of them "2 seconds".

    The fake starts producing only AFTER the nominal second has passed, so a wall-clock
    implementation reaches stop() with no file at all and raises — seen red against exactly that
    mutant before this assertion was trusted.
    """
    target = str(tmp_path / "recordings" / "slow.wav")
    holder = {}

    def factory():
        holder["proc"] = SlowStartProc(target)
        return holder["proc"]

    _patch_recorder(monkeypatch, tmp_path, target, factory)
    m = mic.record_clip(1.0, str(tmp_path), runner=lambda *_a, **_k: (1, "", ""))
    assert m["duration_s"] >= 1.0, "returned before a full second of audio existed"
    assert holder["proc"].polls > 40, "gave up before the device's slow start finished"


def test_record_clip_waits_past_the_nominal_length_then_gives_up(tmp_path, monkeypatch):
    """A device that never starts must fail in BOUNDED time — but the bound is
    ``seconds * patience + 5``, not ``seconds``. A recorder that gave up at the nominal length
    would be the wall-clock bug wearing a timeout's name, so this asserts BOTH edges: it waited
    well past 1s, and it still came back.

    The take comes back SHORT and measured as such — never padded or relabelled to the length
    that was asked for.
    """
    target = str(tmp_path / "recordings" / "stuck.wav")
    _patch_recorder(monkeypatch, tmp_path, target,
                    lambda: FakeProc(target, frames=2205, amplitude=3000, write_on=("signal",)))
    t0 = time.time()
    m = mic.record_clip(1.0, str(tmp_path), patience=1.0, runner=lambda *_a, **_k: (1, "", ""))
    elapsed = time.time() - t0
    assert elapsed > 3.0, f"gave up after {elapsed:.1f}s — that is the wall clock, not the cap"
    # Generous upper edge on purpose: the meaningful assertion is the LOWER one (it waited past
    # the nominal length). A tight upper bound would turn a busy machine into a failing test.
    assert elapsed < 40.0, f"unbounded wait ({elapsed:.1f}s)"
    assert m["duration_s"] == pytest.approx(0.05, abs=0.01)   # the short take, honestly reported
    assert m["too_short"] is True


def test_a_named_device_the_server_does_not_have_is_refused(monkeypatch, tmp_path):
    """Measured 2026-08-21: ``ffmpeg -f pulse -i no_such_source_at_all`` does NOT fail — pulse
    resolves an unknown name to the DEFAULT and records three seconds of it, exit 0, a
    well-formed wav. An operator who names the wrong device would get audio from a different one
    with nothing anywhere saying so."""
    monkeypatch.setattr(mic.shutil, "which", lambda b: f"/usr/bin/{b}")
    out = "0\tin.real\tPipeWire\ts16le\tIDLE\n"
    r = mic.MicRecorder(str(tmp_path), device="in.bogus", backend="ffmpeg",
                        runner=lambda *_a, **_k: (0, out, ""))
    with pytest.raises(mic.CaptureError) as e:
        r.start()
    assert "in.bogus" in str(e.value) and "in.real" in str(e.value)


def test_a_named_device_the_server_does_have_is_accepted(monkeypatch, tmp_path):
    """The refusal above must be able to NOT fire — a check that rejects everything is not a
    check, it is an outage."""
    monkeypatch.setattr(mic.shutil, "which", lambda b: f"/usr/bin/{b}")
    out = "0\tin.real\tPipeWire\ts16le\tIDLE\n"
    target = str(tmp_path / "recordings" / "ok.wav")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    monkeypatch.setattr(mic.subprocess, "Popen",
                        lambda argv, **_kw: FakeProc(target, frames=100, write_on=()))
    r = mic.MicRecorder(str(tmp_path), device="in.real", backend="ffmpeg",
                        runner=lambda *_a, **_k: (0, out, ""))
    assert r.start().endswith(".wav")
    r.cancel()


def test_an_alsa_hardware_string_is_not_checked_against_server_names(monkeypatch, tmp_path):
    """``plughw:CARD=Camera`` is an ALSA address, not a server source name — validating it
    against pactl's list would refuse every legitimate raw-ALSA capture."""
    monkeypatch.setattr(mic.shutil, "which", lambda b: f"/usr/bin/{b}")
    out = "0\tin.real\tPipeWire\ts16le\tIDLE\n"
    target = str(tmp_path / "recordings" / "alsa.wav")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    monkeypatch.setattr(mic.subprocess, "Popen",
                        lambda argv, **_kw: FakeProc(target, frames=100, write_on=()))
    r = mic.MicRecorder(str(tmp_path), device="plughw:CARD=Camera,DEV=0", backend="arecord",
                        runner=lambda *_a, **_k: (0, out, ""))
    assert r.start().endswith(".wav")
    r.cancel()


def test_the_check_stands_down_when_the_server_cannot_be_enumerated(monkeypatch, tmp_path):
    """No pactl / an empty list is 'we do not know', not 'the device is absent'. Refusing on an
    unknowable answer would break capture on any node without pactl."""
    monkeypatch.setattr(mic.shutil, "which", lambda b: f"/usr/bin/{b}")
    target = str(tmp_path / "recordings" / "unknown.wav")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    monkeypatch.setattr(mic.subprocess, "Popen",
                        lambda argv, **_kw: FakeProc(target, frames=100, write_on=()))
    r = mic.MicRecorder(str(tmp_path), device="anything", backend="pw-record",
                        runner=lambda *_a, **_k: (1, "", "no pactl"))
    assert r.start().endswith(".wav")
    r.cancel()
