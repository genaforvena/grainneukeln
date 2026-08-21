"""The LAN pult — the phone-reachable control surface.

Two halves, as with the mic:

* **Pult** (no HTTP) — the verbs and their refusals.
* **The server**, driven over a REAL socket with ``urllib``. A route table asserted by reading the
  dict is source text, not behaviour; these tests bind a port, speak HTTP to it, and read what
  comes back. That is the only version of "the pult works" that means anything.
"""

import json
import os
import socket
import threading
import unittest
import urllib.error
import urllib.request

from pult import server as pult_mod
from pult.server import Pult, PultBusy, make_server, safe_join


class _FakeCutter:
    """Carries the attributes ``engine.build_config`` actually reads — the pult builds a REAL
    AutoMixerConfig, so a fake that only has ``beats`` would fail inside the config builder and
    every assertion about the run would be measuring that instead."""

    def __init__(self, path="/tmp/x.wav"):
        import numpy as np
        from pydub import AudioSegment
        self.audio_file_path = path
        self.beats = np.asarray([0, 500, 1000])
        self.beat = 500
        self.step = 500
        self.audio = AudioSegment.silent(duration=1500)
        self.audio2 = None
        self.low_memory = False


class FakeRecorder:
    def __init__(self, out_dir, device=None, measurement=None, path="/tmp/rec/take.wav"):
        self.out_dir, self.device = out_dir, device
        self.backend = "fake"
        self.path = path
        self.recording = False
        self.cancelled = False
        self._m = measurement

    def start(self):
        self.recording = True
        return self.path

    def stop(self):
        self.recording = False
        return self._m

    def cancel(self):
        self.recording = False
        self.cancelled = True

    def elapsed(self):
        return 1.5


def measurement(path="/tmp/rec/take.wav", silent=False, too_short=False, rms=4000):
    return {"path": path, "duration_s": 3.0, "rate": 44100, "channels": 1, "frames": 132300,
            "rms": rms, "peak": rms * 2, "silent": silent, "too_short": too_short,
            "backend": "fake", "device": None, "holders": []}


def _pult(tmp, **kw):
    kw.setdefault("loader", lambda v, on_stage=None: _FakeCutter(v))
    kw.setdefault("runner", lambda *a, **k: os.path.join(tmp, "grain_cut100.mp3"))
    return Pult(tmp, session_path=os.path.join(tmp, "session.json"), **kw)


# ─── path jail ────────────────────────────────────────────────────────────────

class SafeJoinTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def test_a_file_inside_the_root_resolves(self):
        p = os.path.join(self.tmp, "a.mp3")
        open(p, "wb").write(b"x")
        self.assertEqual(safe_join(self.tmp, "a.mp3"), os.path.realpath(p))

    def test_dotdot_escapes_are_refused(self):
        self.assertIsNone(safe_join(self.tmp, "../../etc/passwd"))
        self.assertIsNone(safe_join(self.tmp, "a/../../../etc/passwd"))

    def test_an_absolute_path_cannot_override_the_root(self):
        self.assertIsNone(safe_join(self.tmp, "/etc/passwd"))

    def test_a_symlink_pointing_out_of_the_tree_is_refused(self):
        """The reason this is realpath and not startswith: a prefix check passes a symlink whose
        NAME is inside the root and whose TARGET is anywhere on the disk."""
        link = os.path.join(self.tmp, "escape")
        os.symlink("/etc", link)
        self.assertIsNone(safe_join(self.tmp, "escape/passwd"))

    def test_the_root_itself_is_not_servable(self):
        self.assertIsNone(safe_join(self.tmp, ""))


# ─── verbs ────────────────────────────────────────────────────────────────────

class PultVerbsTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def test_a_take_with_signal_becomes_the_source(self):
        take = os.path.join(self.tmp, "recordings", "good.wav")
        os.makedirs(os.path.dirname(take), exist_ok=True)
        open(take, "wb").write(b"RIFF")
        rec = FakeRecorder(self.tmp, measurement=measurement(path=take), path=take)
        p = _pult(self.tmp, recorder_factory=lambda o, d: rec)
        p.record_start()
        out = p.record_stop()
        self.assertTrue(out["loaded"])
        _join_workers()
        self.assertIsNotNone(p.state.cutter)

    def test_a_silent_take_is_kept_and_named_but_not_loaded(self):
        """Same rule as the TUI and the CLI — three surfaces, one rule. A phone that auto-loaded
        silence would leave the operator pressing GRIND on zeros."""
        rec = FakeRecorder(self.tmp, measurement=measurement(path="/tmp/dead.wav", silent=True,
                                                            rms=1))
        p = _pult(self.tmp, recorder_factory=lambda o, d: rec)
        p.record_start()
        out = p.record_stop()
        self.assertFalse(out["loaded"])
        self.assertIn("SILENT", out["line"])
        self.assertIn("/tmp/dead.wav", p.message)
        self.assertIsNone(p.state.cutter)

    def test_a_second_record_press_is_refused_not_queued(self):
        rec = FakeRecorder(self.tmp, measurement=measurement())
        p = _pult(self.tmp, recorder_factory=lambda o, d: rec)
        p.record_start()
        with self.assertRaises(PultBusy):
            p.record_start()

    def test_stop_without_start_is_refused(self):
        p = _pult(self.tmp)
        with self.assertRaises(PultBusy):
            p.record_stop()

    def test_run_is_refused_while_recording(self):
        """A grind while the mic is open competes for the same CPU that is servicing a realtime
        capture, and the take is what gets dropped."""
        rec = FakeRecorder(self.tmp, measurement=measurement())
        p = _pult(self.tmp, recorder_factory=lambda o, d: rec)
        p.load_source("/tmp/x.wav")
        _join_workers()
        p.state.sample_length_ms = 200
        p.record_start()
        with self.assertRaises(PultBusy) as e:
            p.run()
        self.assertIn("recording", str(e.exception))

    def test_run_is_refused_with_no_source_and_says_why(self):
        p = _pult(self.tmp)
        with self.assertRaises(PultBusy) as e:
            p.run()
        self.assertIn("source", str(e.exception).lower())

    def test_run_renders_and_names_the_output(self):
        out_path = os.path.join(self.tmp, "grain_cut200_x.mp3")
        p = _pult(self.tmp, runner=lambda *a, **k: out_path)
        p.load_source("/tmp/x.wav")
        _join_workers()
        p.state.sample_length_ms = 200
        p.run()
        _join_workers()
        self.assertEqual(p.last_output, out_path)
        self.assertIsNone(p.busy)
        self.assertIn("grain_cut200", p.message)

    def test_a_grind_failure_names_the_exception_instead_of_hanging_busy(self):
        """A phone screen stuck on 'grinding…' forever is the worst outcome — the operator cannot
        tell a long render from a dead one."""
        def boom(*a, **k):
            raise MemoryError("out of memory")
        p = _pult(self.tmp, runner=boom)
        p.load_source("/tmp/x.wav")
        _join_workers()
        p.state.sample_length_ms = 200
        p.run()
        _join_workers()
        self.assertIsNone(p.busy)
        self.assertIn("MemoryError", p.error)

    def test_amc_line_applies_and_persists_to_the_shared_session(self):
        """The pult is not a remote control for a running TUI — it shares the TUI's checkpoint
        file, so a param set on the phone is there when the TUI next starts."""
        p = _pult(self.tmp)
        p.state.sample_length_ms = 400
        p.apply_amc("l /2 s 0.9")
        self.assertEqual(p.state.sample_length_ms, 200)
        from tui.state import SessionState
        reread = SessionState.load(os.path.join(self.tmp, "session.json"))
        self.assertEqual(reread.sample_length_ms, 200)
        self.assertEqual(reread.speed, 0.9)

    def test_a_bad_amc_token_is_reported_and_never_silently_swallowed(self):
        """Partial-apply is the TUI command bar's inherited contract (the good half applies), so
        the thing that can go wrong here is a typo that LOOKS applied. The bad token must come
        back in the response and land in the status line the phone polls."""
        p = _pult(self.tmp)
        p.state.sample_length_ms = 400
        out = p.apply_amc("l 200 nonsense_token 5")
        self.assertEqual(p.state.sample_length_ms, 200)          # the good half applied
        self.assertTrue(out["errors"])
        self.assertIn("nonsense_token", out["errors"][0])
        self.assertIn("nonsense_token", p.error)                 # and it is visible to the phone
        self.assertIn("nonsense_token", p.snapshot()["error"])

    def test_a_clean_amc_line_leaves_no_error_behind(self):
        """A gate that can only ever report a problem is not a gate."""
        p = _pult(self.tmp)
        p.state.sample_length_ms = 400
        out = p.apply_amc("l /2 s 0.9")
        self.assertEqual(out["errors"], [])
        self.assertIsNone(p.error)

    def test_a_take_name_resolves_against_the_output_dir_not_the_cwd(self):
        """The phone lists takes as ``recordings/<name>``; the pult may have been started from
        anywhere, so a bare relative path would resolve to a file that does not exist."""
        take = os.path.join(self.tmp, "recordings", "t.wav")
        os.makedirs(os.path.dirname(take), exist_ok=True)
        open(take, "wb").write(b"RIFF")
        p = _pult(self.tmp)
        self.assertEqual(p.resolve_source("recordings/t.wav"), os.path.realpath(take))

    def test_free_text_passes_through_so_search_still_works(self):
        p = _pult(self.tmp)
        self.assertEqual(p.resolve_source("Aphex Twin - Rhubarb"), "Aphex Twin - Rhubarb")
        self.assertEqual(p.resolve_source("https://x/y"), "https://x/y")

    def test_a_relative_path_cannot_escape_the_output_dir(self):
        p = _pult(self.tmp)
        # Passes through as free text (the loader will fail honestly) rather than being resolved
        # to a file outside the tree.
        self.assertEqual(p.resolve_source("../../etc/passwd"), "../../etc/passwd")

    def test_outputs_and_takes_are_listed_separately(self):
        """Merging them makes the newest render unfindable after a burst of takes."""
        open(os.path.join(self.tmp, "grain_cut1.mp3"), "wb").write(b"x")
        os.makedirs(os.path.join(self.tmp, "recordings"), exist_ok=True)
        open(os.path.join(self.tmp, "recordings", "rec-1.wav"), "wb").write(b"x")
        p = _pult(self.tmp)
        self.assertEqual([r["name"] for r in p.outputs()], ["grain_cut1.mp3"])
        self.assertEqual([r["name"] for r in p.takes()], ["rec-1.wav"])

    def test_snapshot_is_json_serialisable_with_a_holder_row(self):
        m = measurement(silent=True)
        m["holders"] = [{"pid": 7, "device": "pcmC0D0c", "command": "arecord -D plughw " * 20}]
        rec = FakeRecorder(self.tmp, measurement=m)
        p = _pult(self.tmp, recorder_factory=lambda o, d: rec)
        p.record_start()
        p.record_stop()
        blob = json.dumps(p.snapshot())          # raises if anything in there is not JSON
        self.assertIn("pcmC0D0c", blob)
        self.assertLessEqual(len(p.snapshot()["last_take"]["holders"][0]["command"]), 80)


# ─── over a real socket ───────────────────────────────────────────────────────

class PultHTTPTest(unittest.TestCase):
    """Binds a real port and speaks real HTTP. A route table read out of a dict is source text;
    this is behaviour."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.rec = FakeRecorder(self.tmp, measurement=measurement())
        self.pult = _pult(self.tmp, recorder_factory=lambda o, d: self.rec)
        self.httpd = make_server(self.pult, host="127.0.0.1", port=0, token="tok-123")
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def _req(self, path, body=None, token="tok-123", method=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
        if token is not None:
            req.add_header("X-Pult-Token", token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw or b"{}")
            except ValueError:
                return e.code, {"raw": raw[:200].decode("utf-8", "replace")}

    def test_the_page_is_served_without_a_token_but_the_api_is_not(self):
        """The page itself carries no state and no verbs — it is the thing that ASKS for the
        token. Every route that can do something requires it."""
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=10) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("grainneukeln", r.read().decode())
        for path in ("/api/state", "/audio/x.mp3"):
            code, body = self._req(path, token=None)
            self.assertEqual(code, 403, path)
            self.assertIn("token", body["error"])

    def test_a_wrong_token_is_refused_on_every_verb(self):
        for path in ("/api/record/start", "/api/run", "/api/amc", "/api/source"):
            code, _ = self._req(path, {}, token="not-the-token")
            self.assertEqual(code, 403, path)

    def test_a_token_in_the_query_string_works_for_the_first_hit(self):
        """The phone gets the token in the URL (typed or scanned) before it has anywhere to keep
        it; after that the page sends a header."""
        code, body = self._req("/api/state?t=tok-123", token=None)
        self.assertEqual(code, 200)
        self.assertIn("outputs", body)

    def test_record_start_and_stop_over_http(self):
        code, body = self._req("/api/record/start", {})
        self.assertEqual(code, 200)
        self.assertTrue(body["state"]["recording"])
        code, body = self._req("/api/record/stop", {})
        self.assertEqual(code, 200)
        self.assertTrue(body["result"]["loaded"])
        self.assertFalse(body["state"]["recording"])

    def test_a_refusal_is_409_with_a_reason_not_a_500(self):
        """A refusal the phone can render as a sentence, rather than 'the server broke'."""
        self._req("/api/record/start", {})
        code, body = self._req("/api/record/start", {})
        self.assertEqual(code, 409)
        self.assertIn("already recording", body["error"])
        self.assertIn("state", body)      # the phone still gets a fresh state to re-render

    def test_run_with_no_source_is_409_and_names_the_missing_thing(self):
        code, body = self._req("/api/run", {})
        self.assertEqual(code, 409)
        self.assertIn("source", body["error"].lower())

    def test_audio_is_served_from_the_output_dir(self):
        p = os.path.join(self.tmp, "grain_cut1.mp3")
        open(p, "wb").write(b"ID3-fake-mp3-bytes")
        url = f"http://127.0.0.1:{self.port}/audio/grain_cut1.mp3?t=tok-123"
        with urllib.request.urlopen(url, timeout=10) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers["Content-Type"], "audio/mpeg")
            self.assertEqual(r.read(), b"ID3-fake-mp3-bytes")

    def test_audio_traversal_is_refused_over_the_wire(self):
        """Not just unit-tested on safe_join — asserted through the actual handler, because the
        jail only counts where the bytes are served."""
        code, _ = self._req("/audio/../../../../etc/passwd")
        self.assertIn(code, (403, 404))
        code, _ = self._req("/audio/%2e%2e%2f%2e%2e%2fetc%2fpasswd")
        self.assertIn(code, (403, 404))

    def test_an_unknown_route_is_404_not_a_traceback(self):
        code, body = self._req("/api/nope", {})
        self.assertEqual(code, 404)
        self.assertIn("error", body)

    def test_bad_json_is_rejected_cleanly(self):
        url = f"http://127.0.0.1:{self.port}/api/run"
        req = urllib.request.Request(url, data=b"{not json", method="POST")
        req.add_header("X-Pult-Token", "tok-123")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        self.assertEqual(code, 400)

    def test_the_page_never_contains_the_token(self):
        """The token reaches the browser through the URL the operator opened, not baked into the
        served HTML — otherwise anyone who can GET / has it."""
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url, timeout=10) as r:
            page = r.read().decode()
        self.assertNotIn("tok-123", page)


class LanAddressTest(unittest.TestCase):
    """Which address to print is the difference between a URL the phone can open and one it
    cannot — and on any node with an overlay the obvious probe gets it wrong."""

    def test_every_returned_address_is_a_real_dotted_quad(self):
        for ip in pult_mod.lan_addresses():
            socket.inet_aton(ip)          # raises if it is not
        ip = pult_mod.lan_ip()
        if ip is not None:
            socket.inet_aton(ip)

    def test_an_rfc1918_address_outranks_a_tailscale_one(self):
        """Measured 2026-08-21: the routing-table probe answered 100.81.222.19 (Tailscale, where
        the default route goes) while the phone was on the LAN at 192.168.8.x — a headline URL
        unreachable from the device it was printed for."""
        ranked = sorted(["100.81.222.19", "192.168.8.224", "172.17.0.1"],
                        key=pult_mod._address_rank)
        self.assertEqual(ranked[0], "192.168.8.224")
        self.assertEqual(ranked[-1], "100.81.222.19")

    def test_cgnat_is_ranked_below_private_but_above_link_local(self):
        r = pult_mod._address_rank
        self.assertLess(r("10.0.0.5"), r("100.100.1.1"))
        self.assertLess(r("100.100.1.1"), r("169.254.9.9"))

    def test_172_16_is_private_but_172_32_is_not(self):
        """The 172 private block is 172.16/12, not all of 172/8 — a prefix check on '172.' would
        rank a public address as LAN."""
        r = pult_mod._address_rank
        self.assertLess(r("172.20.1.1"), r("172.32.1.1"))

    def test_lan_addresses_returns_a_list_not_a_fabricated_single(self):
        """[] is a real answer — the caller prints the bind address rather than a URL that
        cannot work."""
        self.assertIsInstance(pult_mod.lan_addresses(), list)


def _join_workers(timeout=10):
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon and t.name.startswith("Thread-"):
            t.join(timeout=timeout)


if __name__ == "__main__":
    unittest.main()
