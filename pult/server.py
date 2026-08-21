"""The pult — a phone-reachable control surface for grainneukeln over the LAN.

Operator ask 2026-08-21: after the RECORD button, "a control surface reachable from the phone —
LAN web pult first, APK later". This is the pult. It is the same three verbs the TUI has —
**record · load · grind** — reachable from a browser on the same network, plus listening to what
came out.

Design decisions worth keeping:

* **Stdlib only.** ``http.server`` + a single self-contained HTML page. Adding Flask/FastAPI to a
  granular sampler's dependency list to serve four endpoints is a cost the operator pays forever
  on every node and every friend-shippable bundle.

* **It owns its own session, and shares the TUI's checkpoint file.** The pult is NOT a remote
  control for a running TUI — there is no IPC into a Textual app, and inventing one would make
  the phone's buttons work only when a particular tmux pane happens to be alive. It loads and
  saves the same ``SessionState`` JSON the TUI checkpoints to, so params set on the phone are
  there when the TUI next starts, and vice versa.

* **Token-gated, and the token is not optional.** Binding to 0.0.0.0 is the whole point (a phone
  has to reach it), and a LAN is not a trusted room — this node's LAN carries an unlocked router
  and whatever else is on the wifi. Every ``/api`` and ``/audio`` request needs the token;
  comparison is constant-time. A token is generated per launch unless ``$GRAINNEUKELN_PULT_TOKEN``
  pins one.

* **Serving files is path-jailed by REALPATH, not by prefix.** ``output/`` holds operator media
  and a naive ``startswith`` check is defeated by ``..`` and by a symlink pointing out of the
  tree. Everything served is resolved and then required to sit under the resolved root.

* **A busy state is reported, never queued.** One grind and one take at a time; a second press
  gets a clear "already running", because a queue the phone cannot see is a worse lie than a
  refusal it can.
"""

import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from capture import mic
from tui import amc as amc_mod
from tui import engine
from tui.state import SessionState, SESSION_PATH

DEFAULT_PORT = 8731
# Where index.html lives. Under PyInstaller the source tree is unpacked to sys._MEIPASS and the
# module's own __file__ points inside the archive, so the data file must be resolved from the
# bundle root instead — otherwise --pult serves a traceback from a friend's build only.
HERE = os.path.join(sys._MEIPASS, "pult") if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS") \
    else os.path.dirname(os.path.abspath(__file__))


def _connect_trick():
    """The routing table's answer for 'what source address reaches the world'. No packet is sent.

    Kept only as a FALLBACK: on any node with a VPN or an overlay it answers with the overlay's
    address, because that is where the default route goes. Measured here — it returned this
    node's Tailscale address (100.81.222.19) while the phone was on the LAN at 192.168.8.x, so
    the URL it produced was unreachable from the device it was printed for.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            return [s.getsockname()[0]]
        finally:
            s.close()
    except OSError:
        return []


def _address_rank(ip):
    """Lower sorts first. A phone joins the WIFI, so an RFC1918 address is what it can reach; a
    CGNAT address (100.64/10 — Tailscale and carrier NAT both live there) is reachable only from
    something already on that overlay, so it is offered LAST and never as the headline."""
    if ip.startswith("192.168."):
        return 0
    if ip.startswith("10."):
        return 1
    try:
        second = int(ip.split(".")[1])
    except (IndexError, ValueError):
        return 5
    if ip.startswith("172.") and 16 <= second <= 31:
        return 1
    if ip.startswith("100.") and 64 <= second <= 127:
        return 4                     # CGNAT / Tailscale — real, but not "the LAN"
    if ip.startswith("169.254."):
        return 6                     # link-local: an address that means DHCP failed
    return 3                         # a public address: real, and a reason to double-check


def lan_addresses():
    """Every IPv4 address this host answers on, best-for-a-phone first. Never a single guess.

    Returns ``[]`` rather than fabricating one, so the caller prints the bind address instead of
    a URL that cannot work.
    """
    found = []
    try:
        p = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"],
                           capture_output=True, text=True, timeout=5)
        if p.returncode == 0:
            for line in p.stdout.splitlines():
                parts = line.split()
                if "inet" in parts:
                    addr = parts[parts.index("inet") + 1].split("/")[0]
                    if addr not in found:
                        found.append(addr)
    except (OSError, subprocess.SubprocessError):
        pass
    for addr in _connect_trick():
        if addr not in found:
            found.append(addr)
    return sorted(found, key=_address_rank)


def lan_ip():
    """The single best address to hand a phone, or None."""
    addrs = lan_addresses()
    return addrs[0] if addrs else None


class Pult:
    """The pult's own state and verbs. Holds no HTTP — so it is testable without a socket."""

    def __init__(self, output_dir, session_path=SESSION_PATH, recorder_factory=None,
                 loader=None, runner=None):
        self.output_dir = os.path.abspath(output_dir)
        self.session_path = session_path
        self.state = SessionState.load(session_path) or SessionState(output_dir=self.output_dir)
        self.state.output_dir = self.output_dir
        self.state.cutter = None
        self._recorder_factory = recorder_factory or (
            lambda out_dir, device: mic.MicRecorder(out_dir, device=device))
        self._loader = loader or _default_loader
        self._runner = runner or engine.run
        self._lock = threading.Lock()
        self.recorder = None
        self.last_take = None
        self.busy = None            # None | "loading" | "grinding"
        self.progress = 0.0
        self.message = "ready"
        self.last_output = None
        self.error = None

    # -- record --

    def record_start(self, device=None):
        with self._lock:
            if self.recorder is not None:
                raise PultBusy("already recording")
            if self.busy:
                raise PultBusy(f"busy: {self.busy}")
            recorder = self._recorder_factory(self.output_dir, device)
            path = recorder.start()
            self.recorder = recorder
            self.message = f"● recording via {getattr(recorder, 'backend', '?')}"
            self.error = None
            return {"path": path, "backend": getattr(recorder, "backend", None)}

    def record_stop(self):
        with self._lock:
            recorder = self.recorder
            if recorder is None:
                raise PultBusy("not recording")
            self.recorder = None
        m = recorder.stop()
        self.last_take = m
        line = mic.describe(m, m.get("holders"))
        if m["silent"] or m["too_short"]:
            # Same refusal as the TUI and the CLI: a take with no signal is kept and named, never
            # promoted to "the source". Three surfaces, one rule.
            self.message = f"{line} · kept at {m['path']}"
            self.error = line
            return {"measurement": _jsonable(m), "loaded": False, "line": line}
        self.message = f"recorded {line}"
        self.error = None
        self.load_source(m["path"])
        return {"measurement": _jsonable(m), "loaded": True, "line": line}

    def record_cancel(self):
        with self._lock:
            recorder, self.recorder = self.recorder, None
        if recorder is None:
            raise PultBusy("not recording")
        recorder.cancel()
        self.message = "take discarded"
        return {"cancelled": True}

    # -- source --

    def resolve_source(self, value):
        """Turn what the phone sent into what the loader can open.

        A URL and an absolute path pass through. A RELATIVE path is resolved against the output
        dir, not against the process cwd — the phone lists takes as ``recordings/<name>`` and the
        pult may have been started from anywhere, so a bare relative path would resolve to a file
        that does not exist and surface as "load failed" for a take the phone can plainly see.
        A relative path that does not exist there is passed through unchanged, so free-text
        searches ("artist - track") still reach the searcher.
        """
        value = (value or "").strip()
        if not value:
            raise PultBusy("nothing to load")
        if value.startswith(("http://", "https://")) or os.path.isabs(value):
            return value
        candidate = safe_join(self.output_dir, value)
        if candidate and os.path.isfile(candidate):
            return candidate
        return value

    def load_source(self, value):
        value = self.resolve_source(value)
        with self._lock:
            if self.busy:
                raise PultBusy(f"busy: {self.busy}")
            self.busy = "loading"
        self.message = f"loading {os.path.basename(value) or value}…"
        self.error = None
        threading.Thread(target=self._load_worker, args=(value,), daemon=True).start()
        return {"loading": value}

    def _load_worker(self, value):
        try:
            cutter = self._loader(value, lambda t: setattr(self, "message", t))
        except Exception as e:
            self.error = f"load failed: {e}"
            self.message = self.error
            self.busy = None
            return
        self.state.cutter = cutter
        self.state.source_path = getattr(cutter, "audio_file_path", value)
        beat = int(getattr(cutter, "beat", 0) or 0)
        base = beat if beat > 0 else int(getattr(cutter, "step", 0) or 0)
        if base > 0 and not self.state.sample_length_ms:
            self.state.sample_length_ms = base
        beats = getattr(cutter, "beats", None)
        n = len(beats) if beats is not None else 0
        self.message = f"✓ loaded {os.path.basename(self.state.source_path)} · {n} beats"
        self.busy = None
        self.save()

    # -- params --

    def apply_amc(self, line):
        """Apply an amc line — the same grammar the TUI's command bar and the CLI both parse.

        Partial-apply semantics are INHERITED, not invented here: ``amc.apply_amc`` writes every
        token that parsed and returns the rest as errors, so a mostly-right line still moves the
        knobs the operator got right. The pult's job is to make sure the bad half is not silent —
        the errors come back in the response AND land in the status line the phone polls, so a
        typo cannot look like an applied setting.
        """
        errors = amc_mod.apply_amc(self.state, line)
        self.save()
        if errors:
            self.error = "; ".join(errors)
            self.message = f"amc: {self.error}"
        else:
            self.error = None
            self.message = f"amc {amc_mod.format_amc(self.state)}"
        return {"amc": amc_mod.format_amc(self.state), "errors": errors}

    def save(self):
        self.state.save(self.session_path)

    # -- grind --

    def run(self):
        with self._lock:
            if self.busy:
                raise PultBusy(f"busy: {self.busy}")
            if self.recorder is not None:
                raise PultBusy("still recording — stop the take first")
            ok, why = self.state.is_runnable()
            if not ok:
                raise PultBusy(why)
            self.busy = "grinding"
        self.progress = 0.0
        self.error = None
        self.message = "grinding…"
        threading.Thread(target=self._run_worker, daemon=True).start()
        return {"running": True}

    def _run_worker(self):
        try:
            config = engine.build_config(self.state.cutter, self.state)
            path = self._runner(config, self.output_dir,
                                on_progress=lambda p: setattr(self, "progress", float(p)),
                                wav_export=self.state.wav_export,
                                source_path=self.state.source_path)
            self.last_output = path
            self.progress = 1.0
            self.message = f"✓ {os.path.basename(path)}"
        except Exception as e:
            # The traceback goes to the crash log (engine.run already wrote the recipe); the phone
            # gets the message. A phone screen showing "error" with no name is a dead end.
            self.error = f"{type(e).__name__}: {e}"
            self.message = self.error
            traceback.print_exc()
        finally:
            self.busy = None

    # -- read models --

    def outputs(self, limit=30):
        """Rendered mp3/wav under the output dir, newest first. Recordings are listed separately —
        a take and a render are different things and merging them makes the newest render
        unfindable after a burst of takes."""
        return _listing(self.output_dir, (".mp3", ".wav"), limit, recursive=False)

    def takes(self, limit=15):
        return _listing(os.path.join(self.output_dir, "recordings"), (".wav",), limit,
                        recursive=False)

    def devices(self):
        try:
            return mic.list_devices()
        except Exception:
            return []

    def snapshot(self):
        rec = self.recorder
        return {
            "recording": rec is not None and rec.recording,
            "elapsed": round(rec.elapsed(), 1) if rec is not None else 0.0,
            "backend": getattr(rec, "backend", None) if rec is not None else None,
            "busy": self.busy,
            "progress": round(self.progress, 3),
            "message": self.message,
            "error": self.error,
            "source": os.path.basename(self.state.source_path or "") or None,
            "source_loaded": self.state.cutter is not None,
            "amc": amc_mod.format_amc(self.state),
            "sample_length_ms": self.state.sample_length_ms,
            "mode": self.state.mode,
            "last_output": os.path.basename(self.last_output) if self.last_output else None,
            "last_take": _jsonable(self.last_take) if self.last_take else None,
            "outputs": self.outputs(),
            "takes": self.takes(),
            "devices": self.devices(),
        }


class PultBusy(RuntimeError):
    """A refusal the phone can read. Never a queue — see the module docstring."""


def _jsonable(m):
    if not m:
        return None
    out = {k: v for k, v in m.items() if k != "holders"}
    out["holders"] = [{"pid": h["pid"], "device": h["device"], "command": h["command"][:80]}
                      for h in (m.get("holders") or [])]
    return out


def _listing(root, exts, limit, recursive=False):
    if not os.path.isdir(root):
        return []
    rows = []
    for name in os.listdir(root):
        if not name.lower().endswith(exts):
            continue
        path = os.path.join(root, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        if not os.path.isfile(path):
            continue
        rows.append({"name": name, "size": st.st_size, "mtime": int(st.st_mtime)})
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows[:limit]


def _default_loader(value, on_stage=None):
    from tui.app import _real_loader
    return _real_loader(value, on_stage)


# ─── HTTP ─────────────────────────────────────────────────────────────────────

def safe_join(root, *parts):
    """Resolve ``parts`` under ``root`` or return None.

    REALPATH, not prefix matching: ``output/`` holds operator media, and a ``startswith`` check is
    defeated both by ``..`` and by a symlink inside the tree pointing out of it. Anything that
    does not resolve to a path under the resolved root is refused, including the root itself.
    """
    root_real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, *parts))
    if target == root_real:
        return None
    if os.path.commonpath([root_real, target]) != root_real:
        return None
    return target


class PultHandler(BaseHTTPRequestHandler):
    server_version = "grainneukeln-pult"
    pult = None
    token = ""

    def log_message(self, fmt, *args):
        # One line per request on stderr, with the token stripped: the URL carries the token on
        # the first hit and an access log is exactly the place a secret gets copied into a paste.
        path = self.path.split("?")[0]
        self.server_log(f"{self.address_string()} {self.command} {path} {args[-1] if args else ''}")

    def server_log(self, line):
        print(f"[pult] {line}", flush=True)

    # -- auth --

    def _authed(self, query):
        supplied = self.headers.get("X-Pult-Token") or (query.get("t", [""])[0])
        return secrets.compare_digest(str(supplied), self.token)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _deny(self):
        self._json({"error": "bad or missing token"}, 403)

    # -- routes --

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path
        if path in ("/", "/index.html"):
            return self._page()
        if not self._authed(query):
            return self._deny()
        if path == "/api/state":
            return self._json(self.pult.snapshot())
        if path.startswith("/audio/"):
            return self._audio(path[len("/audio/"):])
        return self._json({"error": "no such route"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._authed(query):
            return self._deny()
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, OSError):
            return self._json({"error": "bad json"}, 400)
        routes = {
            "/api/record/start": lambda: self.pult.record_start(payload.get("device") or None),
            "/api/record/stop": self.pult.record_stop,
            "/api/record/cancel": self.pult.record_cancel,
            "/api/source": lambda: self.pult.load_source(str(payload.get("value") or "").strip()),
            "/api/amc": lambda: self.pult.apply_amc(str(payload.get("line") or "")),
            "/api/run": self.pult.run,
        }
        fn = routes.get(parsed.path)
        if fn is None:
            return self._json({"error": "no such route"}, 404)
        try:
            return self._json({"ok": True, "result": fn(), "state": self.pult.snapshot()})
        except PultBusy as e:
            # 409, not 500: this is a refusal with a reason, and the phone renders it as a
            # message rather than as "the server broke".
            return self._json({"ok": False, "error": str(e), "state": self.pult.snapshot()}, 409)
        except Exception as e:
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}",
                               "state": self.pult.snapshot()}, 400)

    def _audio(self, name):
        root = self.pult.output_dir
        target = safe_join(root, name)
        if target is None or not os.path.isfile(target):
            return self._json({"error": "not found"}, 404)
        ctype = "audio/mpeg" if target.lower().endswith(".mp3") else "audio/wav"
        size = os.path.getsize(target)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "none")
        self.end_headers()
        with open(target, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return          # the phone navigated away mid-stream; not an error

    def _page(self):
        with open(os.path.join(HERE, "index.html"), "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(pult, host="0.0.0.0", port=DEFAULT_PORT, token=None):
    token = token or os.environ.get("GRAINNEUKELN_PULT_TOKEN") or secrets.token_urlsafe(9)
    handler = type("BoundPultHandler", (PultHandler,), {"pult": pult, "token": token})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.pult = pult
    httpd.token = token
    return httpd


def serve(output_dir, host="0.0.0.0", port=DEFAULT_PORT, token=None, session_path=SESSION_PATH):
    pult = Pult(output_dir, session_path=session_path)
    try:
        httpd = make_server(pult, host, port, token)
    except OSError as e:
        # A busy port is the single most common way this command fails (a pult is already up in
        # another pane), and it deserves the one line that says so — not a socketserver traceback
        # that reads as a bug in the tool.
        raise SystemExit(f"pult: cannot bind {host}:{port} — {e.strerror or e}. "
                         f"Another pult may already be running; try --pult <other port>.")
    port_bound = httpd.server_address[1]
    if host in ("0.0.0.0", ""):
        addrs = lan_addresses()
    else:
        addrs = [host]
    print("grainneukeln pult")
    print(f"  output   {pult.output_dir}")
    if addrs:
        print(f"  open     http://{addrs[0]}:{port_bound}/?t={httpd.token}")
        # Every other address this host answers on. A node with a VPN/overlay has several, and
        # which one the phone can reach is a fact about the phone's network, not about this host —
        # so offer them all rather than picking one and being confidently wrong.
        for extra in addrs[1:]:
            print(f"  or       http://{extra}:{port_bound}/?t={httpd.token}")
    else:
        print(f"  open     http://{host}:{port_bound}/?t={httpd.token}")
        print("  (could not read this host's addresses — the URL above uses the bind address)")
    print("  LAN only. The token is in the URL; anyone who can reach this port and has it can "
          "record and grind on this machine.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[pult] stopped")
    finally:
        if pult.recorder is not None:
            # An in-flight take must not outlive the server — the backend is a child process
            # holding a capture device, and orphaning it locks the card for the whole node.
            try:
                pult.record_stop()
            except Exception:
                pass
        httpd.server_close()
    return httpd
