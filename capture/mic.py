"""Live microphone capture — a first-class source alongside yt-dlp/file.

Operator ask 2026-08-21: a RECORD button, so the thing you grind can be the room you are
sitting in rather than something you downloaded.

Three doctrines shape this module, each earned somewhere else in the mesh:

1. **No silent fallback.** ``cmd 2>/dev/null || echo <default>`` turns a total failure into a
   plausible constant. Every rung of the backend ladder is NAMED in the result
   (:attr:`CaptureResult.backend`), and when no rung is available :func:`pick_backend` RAISES
   :class:`CaptureError` listing what it looked for. There is no "it recorded" that is not a wav.

2. **A degenerate capture must be LOUD.** A mic that is muted, unplugged, or already held by
   another process still yields a perfectly well-formed wav full of zeros — indistinguishable
   from a successful recording by every check except the one that looks at the samples. So
   :func:`measure` is not optional decoration: every capture is measured, and a silent one is
   reported as silent (with :func:`who_holds_capture` naming the contender when there is one).
   On this node that contender is real — ``mesh-overhear`` holds the USB camera mic through raw
   ALSA (``plughw:CARD=Camera``), which locks PipeWire out of that card entirely.

3. **The header is not the file.** A capture is stopped by killing the writer, and every one of
   these tools writes a streaming wav header whose length fields are a placeholder until it
   exits cleanly. A truncated/placeholder header makes ``wave`` report a frame count that is
   either 0 or absurd. :func:`repair_wav_header` rewrites the RIFF/data sizes from the bytes that
   are actually on disk, so the duration you read is the audio you have.
"""

import os
import shutil
import struct
import subprocess
import time
import wave
from datetime import datetime

# Below this RMS (16-bit scale, 0..32767) a capture carries no signal a grinder could use.
# Not zero: a live-but-quiet input floor idles at 1-3 from ADC noise, and calling that "audio"
# is how a dead mic becomes a plausible source. Measured on this node's free ALC897 line-in with
# nothing plugged in: rms 1.
SILENCE_RMS = 8

# What a capture is worth grinding. Shorter than this and the beat-detector has nothing to latch.
MIN_USEFUL_SECONDS = 0.5


class CaptureError(RuntimeError):
    """No capture backend, no capture device, or the recorder died. Always names what was tried."""


# ─── backend ladder ───────────────────────────────────────────────────────────
# Ordered best-first. Each entry: (name, binary, argv-builder, why-this-rung).
# The argv-builder returns the full command writing a wav to ``path``.

def _argv_pw_record(binary, path, device, rate, channels):
    argv = [binary, "--rate", str(rate), "--channels", str(channels), "--format", "s16"]
    if device:
        argv += ["--target", device]
    return argv + [path]


def _argv_parecord(binary, path, device, rate, channels):
    argv = [binary, f"--rate={rate}", f"--channels={channels}",
            "--format=s16le", "--file-format=wav"]
    if device:
        argv += [f"--device={device}"]
    return argv + [path]


def _argv_arecord(binary, path, device, rate, channels):
    argv = [binary, "-f", "S16_LE", "-r", str(rate), "-c", str(channels), "-t", "wav"]
    if device:
        argv += ["-D", device]
    return argv + [path]


def _argv_ffmpeg(binary, path, device, rate, channels):
    return [binary, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "pulse", "-i", device or "default",
            "-ar", str(rate), "-ac", str(channels), "-c:a", "pcm_s16le", path]


BACKENDS = (
    # PipeWire native: coexists with the other clients on the graph, so recording here does not
    # evict the room ear or the browser.
    ("pw-record", "pw-record", _argv_pw_record, "PipeWire native — shares the graph"),
    # Pulse protocol (PipeWire-pulse or real PulseAudio): same coexistence property.
    ("parecord", "parecord", _argv_parecord, "Pulse protocol — shares the server"),
    # ffmpeg's pulse input — same server, but a heavier process. Kept above arecord because it
    # still shares rather than seizes.
    ("ffmpeg", "ffmpeg", _argv_ffmpeg, "ffmpeg via pulse — shares the server"),
    # Raw ALSA: EXCLUSIVE. This rung seizes the card and locks every PipeWire client out of it
    # for the duration. Last on purpose — see who_holds_capture().
    ("arecord", "arecord", _argv_arecord, "raw ALSA — EXCLUSIVE, locks the card"),
)


def available_backends():
    """Every ladder rung whose binary exists here, best-first. Empty list is a real answer."""
    return [{"name": n, "binary": shutil.which(b), "why": why}
            for n, b, _, why in BACKENDS if shutil.which(b)]


def pick_backend(preferred=None):
    """Return ``(name, binary, argv_builder)`` for the best usable backend.

    ``preferred`` names a rung explicitly (an operator who WANTS exclusive ALSA can say so).
    Raises :class:`CaptureError` naming every binary that was looked for when nothing is
    installed — never falls through to a default that cannot record.
    """
    for name, binary, builder, _why in BACKENDS:
        if preferred and name != preferred:
            continue
        found = shutil.which(binary)
        if found:
            return name, found, builder
    if preferred:
        raise CaptureError(
            f"capture backend {preferred!r} not found on PATH "
            f"(available: {', '.join(b['name'] for b in available_backends()) or 'none'})")
    raise CaptureError(
        "no capture backend found — install one of: "
        + ", ".join(b for _n, b, _f, _w in BACKENDS))


# ─── devices ──────────────────────────────────────────────────────────────────

def list_devices(runner=None):
    """Capture sources the audio server will actually hand us, as ``[{id, name}]``.

    Deliberately reports what the SERVER exposes, not what the kernel has: a card seized by a raw
    ALSA client disappears from this list while it is held, and that absence is the truth a
    recorder needs. ``runner`` is injectable for tests.
    """
    run = runner or _run
    devices = []
    if shutil.which("pactl"):
        rc, out, _err = run(["pactl", "list", "short", "sources"])
        if rc == 0:
            for line in out.splitlines():
                fields = line.split("\t")
                if len(fields) < 2:
                    continue
                name = fields[1]
                # A monitor is loopback of an OUTPUT — grinding it records what the node is
                # PLAYING, which is a legitimate source but never the default "mic".
                devices.append({"id": name, "name": name,
                                "monitor": name.endswith(".monitor")})
    return devices


def default_device(runner=None):
    """The first non-monitor source, or None to let the backend choose. None is honest: it means
    'we did not pick', not 'there is no mic'."""
    for d in list_devices(runner=runner):
        if not d["monitor"]:
            return d["id"]
    return None


# A source that is PRESENT is not a source that is LIVE. ``default_device`` returns the first
# non-monitor source PipeWire lists, which is an ORDERING, not a choice — and on mesh-home the first
# one is ``alsa_input.pci-0000_2d_00.4.analog-stereo``, the rear jack with nothing plugged into it:
# measured 2026-08-21, rms 1 / peak 4 out of 32768, i.e. digital silence. The live microphone (the
# USB camera's) is not in that list at all, because the room ear holds its card with an exclusive raw
# ALSA grab. So the button opened a dead source, recorded happily for as long as the operator held
# it, and only THEN said "silent — kept, not loaded". That post-hoc rejection is the whole of
# "кривовато": nothing is wrong until after you have spent your take.
#
# The floor is deliberately at DIGITAL silence, not at "quiet". A hushed room is a legitimate
# recording and must not be refused; an unplugged jack returns near-exact zeros. Distinguishing the
# two is the entire value of the probe, so it is stated as a peak threshold rather than a vibe.
PREFLIGHT_PEAK_FLOOR = 8
PREFLIGHT_SECONDS = 0.4


def probe_device(device, seconds=PREFLIGHT_SECONDS, runner=None, backend=None):
    """Capture a fraction of a second and report whether the source carries ANY signal.

    Returns ``{"peak": int, "rms": int, "dead": bool}``, or ``None`` when the probe itself could not
    run. ``None`` is honest and is NOT ``dead``: "we could not look" and "there is nothing there"
    are different facts, and collapsing them would refuse a take for a reason that never existed.
    """
    import tempfile
    try:
        name, binary, build = pick_backend(backend)
    except Exception:
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        argv = build(binary, tmp.name, device, 16000, 1)
        run = runner or _run
        # A probe that hangs is worse than no probe: it delays the press it exists to make honest.
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            return None
        try:
            proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        m = measure(tmp.name)
        if m is None or m.get("frames", 0) <= 0:
            return None
        return {"peak": m["peak"], "rms": m["rms"], "dead": m["peak"] < PREFLIGHT_PEAK_FLOOR}
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def who_holds_capture(runner=None):
    """Processes currently holding an ALSA capture PCM, as ``[{pid, command}]``.

    This is the named contender behind an inexplicably silent recording. On this node
    ``mesh-overhear``'s ``arecord -D plughw:CARD=Camera`` holds the USB mic continuously, so a
    RECORD that lands on that card gets silence with no error from any layer.
    """
    run = runner or _run
    if not shutil.which("fuser"):
        return []
    holders = []
    snd = "/dev/snd"
    if not os.path.isdir(snd):
        return []
    for node in sorted(os.listdir(snd)):
        # capture PCMs only: pcmC<card>D<dev>c
        if not (node.startswith("pcm") and node.endswith("c")):
            continue
        rc, out, err = run(["fuser", os.path.join(snd, node)])
        if rc != 0:
            continue
        for pid in (out + " " + err).split():
            pid = pid.strip().rstrip("Ffcemrw")
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    cmd = fh.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            except OSError:
                cmd = "?"
            holders.append({"pid": int(pid), "device": node, "command": cmd})
    return holders


def _run(argv, timeout=10):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)


# ─── wav repair + measurement ─────────────────────────────────────────────────

def repair_wav_header(path):
    """Rewrite a streaming wav's RIFF/data sizes from the bytes actually on disk.

    Returns True if the header was corrected. Every backend here writes a placeholder length
    (0, 0xFFFFFFFF, or a stale estimate) that is only finalised on a clean exit — and stopping a
    recording means killing the writer. Without this, ``wave.open`` reports a frame count that is
    not the audio you have, and everything downstream (duration, RMS, the grinder's beat window)
    inherits the lie.
    """
    size = os.path.getsize(path)
    if size < 44:
        return False
    with open(path, "r+b") as fh:
        head = fh.read(12)
        if head[0:4] != b"RIFF" or head[8:12] != b"WAVE":
            return False
        # Walk chunks to find `data` and its declared size.
        pos = 12
        fixed = False
        while pos + 8 <= size:
            fh.seek(pos)
            hdr = fh.read(8)
            if len(hdr) < 8:
                break
            cid, csize = struct.unpack("<4sI", hdr)
            if cid == b"data":
                true_size = size - (pos + 8)
                if csize != true_size:
                    fh.seek(pos + 4)
                    fh.write(struct.pack("<I", true_size))
                    fh.seek(4)
                    fh.write(struct.pack("<I", size - 8))
                    fixed = True
                break
            # A bogus chunk size would walk us off the file; stop rather than loop.
            if csize == 0 or csize > size:
                break
            pos += 8 + csize + (csize & 1)
        return fixed


def measure(path):
    """Measure a captured wav. Never guesses: an unreadable file raises.

    Returns a dict: ``duration_s``, ``rate``, ``channels``, ``frames``, ``rms``, ``peak``,
    ``silent`` (rms below :data:`SILENCE_RMS`), ``too_short``.
    """
    if not os.path.exists(path):
        raise CaptureError(f"no capture at {path}")
    if os.path.getsize(path) < 44:
        raise CaptureError(f"capture at {path} is {os.path.getsize(path)} bytes — no audio at all")
    repair_wav_header(path)
    with wave.open(path, "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        frames = w.getnframes()
        raw = w.readframes(frames)
    duration = frames / float(rate) if rate else 0.0
    rms, peak = _rms_peak(raw, width)
    return {
        "path": path,
        "duration_s": round(duration, 3),
        "rate": rate,
        "channels": channels,
        "frames": frames,
        "rms": rms,
        "peak": peak,
        "silent": rms < SILENCE_RMS,
        "too_short": duration < MIN_USEFUL_SECONDS,
    }


def _rms_peak(raw, width):
    """RMS + peak on the 16-bit scale (0..32767), without pulling in numpy or audioop.

    ``audioop`` is deprecated and gone in 3.13; the arithmetic is four lines, so own it.
    """
    if not raw or width <= 0:
        return 0, 0
    if width == 2:
        n = len(raw) // 2
        if n == 0:
            return 0, 0
        vals = struct.unpack(f"<{n}h", raw[:n * 2])
    elif width == 1:
        # unsigned 8-bit, centred at 128 — rescale to the 16-bit yardstick so SILENCE_RMS means
        # the same thing whatever the backend handed us.
        vals = [(b - 128) * 256 for b in raw]
    else:
        step = width
        vals = []
        for i in range(0, len(raw) - step + 1, step):
            vals.append(int.from_bytes(raw[i + step - 2:i + step], "little", signed=True))
    if not vals:
        return 0, 0
    total = 0
    peak = 0
    for v in vals:
        total += v * v
        a = -v if v < 0 else v
        if a > peak:
            peak = a
    return int((total / len(vals)) ** 0.5), peak


def describe(m, holders=None):
    """One operator-readable line for a measurement. A silent capture SAYS silent, and names the
    process holding a capture device when there is one — the difference between 'the mic is
    broken' and 'something else already has it'."""
    head = (f"{m['duration_s']:.1f}s · {m['rate']}Hz · {m['channels']}ch "
            f"· rms {m['rms']} · peak {m['peak']}")
    # too_short is checked FIRST: a 0-frame take and a take full of zeros are different faults
    # with different fixes (the writer never flushed vs. nothing was on the input), and reporting
    # an empty file as "silent" sends the operator to the mixer instead of to the backend.
    if m["too_short"]:
        return f"TOO SHORT — {head} (under {MIN_USEFUL_SECONDS}s: no pulse to latch)"
    if m["silent"]:
        line = f"SILENT capture — {head} (below rms {SILENCE_RMS}: nothing was on the input)"
        contenders = [h for h in (holders or []) if "grainneukeln" not in h["command"]]
        if contenders:
            h = contenders[0]
            line += f" · {h['device']} is held by pid {h['pid']}: {h['command'][:60]}"
        return line
    return f"✓ {head}"


# ─── the recorder ─────────────────────────────────────────────────────────────

class MicRecorder:
    """Start/stop live capture to a wav under ``<out_dir>/recordings/``.

    Non-blocking by construction: :meth:`start` spawns the backend and returns immediately, so a
    TUI button press does not freeze the UI, and :meth:`elapsed` drives a live timer.
    """

    def __init__(self, out_dir, device=None, rate=44100, channels=1, backend=None,
                 popen=None, runner=None):
        self.out_dir = out_dir
        self.rate = int(rate)
        self.channels = int(channels)
        self._preferred = backend
        self._popen = popen or subprocess.Popen
        self._runner = runner or _run
        self.device = device
        self.backend = None
        self.binary = None
        self.path = None
        self.argv = None
        self._proc = None
        self._t0 = None
        self._t_stop = None

    # -- lifecycle --

    @property
    def recording(self):
        return self._proc is not None and self._proc.poll() is None

    def elapsed(self):
        if self._t0 is None:
            return 0.0
        end = self._t_stop if self._t_stop is not None else time.time()
        return max(0.0, end - self._t0)

    # Backends that address a device by its audio-SERVER name (as opposed to arecord's ALSA
    # `plughw:` syntax, which the server knows nothing about).
    SERVER_ADDRESSED = ("pw-record", "parecord", "ffmpeg")

    def _verify_device(self):
        """Refuse a named device the audio server does not have.

        Measured 2026-08-21: ``ffmpeg -f pulse -i no_such_source_at_all`` does NOT fail — pulse
        resolves an unknown source name to the DEFAULT and ffmpeg records three seconds of it,
        exit 0, a well-formed wav. So an operator who names the wrong device gets audio from a
        different one and nothing anywhere says so. That is the silent-fallback shape: a total
        failure rendered as a plausible success.

        Only enforced when we can actually enumerate (``pactl`` present, list non-empty) and only
        for server-addressed backends — arecord's ``plughw:CARD=…`` is not a server name and must
        pass through untouched.
        """
        if not self.device or self.backend not in self.SERVER_ADDRESSED:
            return
        known = [d["id"] for d in list_devices(runner=self._runner)]
        if known and self.device not in known:
            raise CaptureError(
                f"capture source {self.device!r} is not one this audio server offers. "
                f"Available: {', '.join(known)}. "
                "(A source held by a raw-ALSA client is absent from that list while it is held.)")

    def start(self, name=None):
        """Begin capture. Returns the path being written. Raises CaptureError if it cannot start."""
        if self.recording:
            raise CaptureError("already recording — stop the current take first")
        self.backend, self.binary, builder = pick_backend(self._preferred)
        if self.device is None and self.backend in self.SERVER_ADDRESSED:
            self.device = default_device(runner=self._runner)
        self._verify_device()
        rec_dir = os.path.join(self.out_dir, "recordings")
        os.makedirs(rec_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = os.path.join(rec_dir, f"{name or 'rec'}-{stamp}.wav")
        self.argv = builder(self.binary, self.path, self.device, self.rate, self.channels)
        try:
            self._proc = self._popen(self.argv, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE)
        except OSError as e:
            raise CaptureError(f"could not start {self.backend}: {e}") from e
        self._t0 = time.time()
        self._t_stop = None
        return self.path

    def stop(self, timeout=5.0):
        """End capture and return the MEASUREMENT dict (never a bare path).

        Returning the measurement rather than the path is the point: there is no way to call this
        and receive a silent take without being told it is silent.
        """
        if self._proc is None:
            raise CaptureError("not recording")
        self._t_stop = time.time()
        proc = self._proc
        stderr = b""
        if proc.poll() is None:
            # SIGINT first: every backend here treats it as "finalise and exit", which flushes
            # the last buffer. Escalate only if it does not go.
            try:
                proc.send_signal(2)
                _out, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                _out, stderr = proc.communicate()
            except OSError:
                pass
        else:
            try:
                _out, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                _out, stderr = proc.communicate()
        self._proc = None
        if not os.path.exists(self.path) or os.path.getsize(self.path) < 44:
            err = (stderr or b"").decode("utf-8", "replace").strip()
            raise CaptureError(
                f"{self.backend} wrote no audio to {self.path}"
                + (f" — {err.splitlines()[-1][:200]}" if err else " (and said nothing)"))
        m = measure(self.path)
        m["backend"] = self.backend
        m["device"] = self.device
        m["holders"] = who_holds_capture(runner=self._runner)
        return m

    def cancel(self):
        """Abort a take and delete the partial file. Safe to call when not recording."""
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.kill()
                self._proc.communicate(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass
        self._proc = None
        if self.path and os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass
        self.path = None


def record_clip(seconds, out_dir, patience=3.0, **kw):
    """Blocking capture of ``seconds`` of AUDIO — the CLI/pult/test path. Returns a measurement.

    Waits on BYTES ON DISK, not on the wall clock. The two come apart on a real node: an audio
    device that has been idle sits SUSPENDED, and the backend's stream only starts once the
    server resumes it — measured here, a cold ``--record 2`` returned **0.7s** of audio while a
    warm one returned 2.99s, from identical code. A wall-clock timer would have called both of
    them "2 seconds" and handed a third of a take to the grinder.

    ``patience`` bounds the wait at ``seconds * patience + 5`` so a device that never starts
    fails in bounded time instead of hanging — and when that cap is hit the take is returned
    SHORT and measured as such, never padded or relabelled.
    """
    r = MicRecorder(out_dir, **kw)
    r.start()
    want_bytes = int(float(seconds) * r.rate * r.channels * 2)
    hard_deadline = time.time() + float(seconds) * float(patience) + 5.0
    while time.time() < hard_deadline:
        if not r.recording:
            break
        try:
            # 44 = the smallest canonical wav header; what is past it is audio.
            if os.path.getsize(r.path) - 44 >= want_bytes:
                break
        except OSError:
            pass          # the backend has not created the file yet — keep waiting, bounded
        time.sleep(0.05)
    return r.stop()
