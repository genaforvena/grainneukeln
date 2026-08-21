"""The RECORD button — live mic capture as a first-class source in the TUI.

No test here touches a sound card: the recorder is injected. What they pin is the WIRING, which
is where this feature can fail invisibly — a button that starts nothing and says nothing, a
silent take auto-loaded as if it were audio, a take still running after the app closes.

The capture backend itself is exercised against real hardware in ``capture/test_mic.py``.
"""

import os
import unittest

from textual.app import App, ComposeResult
from textual.widgets import Button

from tui.state import SessionState
from tui.widgets.source_panel import SourcePanel


class _FakeCutter:
    def __init__(self, path="/tmp/rec.wav"):
        import numpy as np
        self.audio_file_path = path
        self.beats = np.asarray([0, 500, 1000])
        self.step = 500


class FakeRecorder:
    """Stands in for ``mic.MicRecorder`` with the same contract: start() -> path,
    stop() -> MEASUREMENT (never a bare path)."""

    def __init__(self, out_dir, device=None, measurement=None, start_error=None,
                 stop_error=None, path="/tmp/rec/take.wav"):
        self.out_dir = out_dir
        self.device = device
        self.backend = "fake"
        self.path = path
        self.recording = False
        self.started = False
        self.stopped = False
        self._measurement = measurement
        self._start_error = start_error
        self._stop_error = stop_error
        self._elapsed = 0.0

    def start(self):
        if self._start_error:
            raise self._start_error
        self.started = True
        self.recording = True
        return self.path

    def stop(self):
        self.stopped = True
        self.recording = False
        if self._stop_error:
            raise self._stop_error
        return self._measurement

    def elapsed(self):
        return self._elapsed


def measurement(path="/tmp/rec/take.wav", silent=False, too_short=False, rms=4000, duration=3.0):
    return {"path": path, "duration_s": duration, "rate": 44100, "channels": 1,
            "frames": int(44100 * duration), "rms": rms, "peak": rms * 2,
            "silent": silent, "too_short": too_short, "backend": "fake", "device": None,
            "holders": []}


class _Host(App):
    def __init__(self, loader=None, recorder=None, state=None):
        super().__init__()
        self._loader = loader or (lambda v: _FakeCutter(v))
        self._recorder = recorder
        self._state = state or SessionState(output_dir="/tmp/gk-test-out")
        self.loaded = None
        self.failed = None
        self.refused = None

    def compose(self) -> ComposeResult:
        yield SourcePanel(self._loader, state=self._state,
                          recorder_factory=lambda out_dir, device: self._recorder)

    def on_source_panel_loaded(self, msg):
        self.loaded = msg.cutter

    def on_source_panel_failed(self, msg):
        self.failed = msg.error

    def on_source_panel_take_refused(self, msg):
        self.refused = msg.reason


async def _settle(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


class RecordButtonTest(unittest.IsolatedAsyncioTestCase):

    async def test_button_press_starts_and_second_press_stops(self):
        """Driven through the real Button, not through toggle_record() — the wiring from a
        pointer event to the recorder is the part that can silently not exist.

        The sleep is not padding: Textual's ``Button._on_click`` drops a click while the widget
        still carries the ``-active`` press-animation class, so two clicks inside that window are
        ONE press (measured 2026-08-21 — six trials, zero stops). Harmless for a REC button (a
        sub-0.2s take is refused as TOO SHORT anyway), but a test that ignores it is flaky, and a
        test that "fixes" the flake by calling the method directly stops testing the button."""
        rec = FakeRecorder("/tmp", measurement=measurement())
        app = _Host(recorder=rec)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            await pilot.click("#record_btn")
            await pilot.pause()
            self.assertTrue(rec.started)
            self.assertTrue(panel.recording)
            self.assertIn("Recording", panel.status_text)
            await pilot.pause(0.4)              # let the press animation clear
            await pilot.click("#record_btn")
            await _settle(app, pilot)
            self.assertTrue(rec.stopped)
            self.assertFalse(panel.recording)

    async def test_a_repeated_start_cannot_open_a_second_take(self):
        """Two starts must yield ONE recorder, so a bounced press cannot orphan a capture process
        holding the card.

        Asserted on the PANEL's own guard rather than on Textual's press-animation debounce: the
        debounce is a wall-clock window, and a test that leans on it passes on an idle machine and
        fails on a loaded one (seen both ways, 2026-08-21). A gate whose verdict depends on how
        busy the box is measures the box."""
        rec = FakeRecorder("/tmp", measurement=measurement())
        made = []

        class _H(_Host):
            def compose(self):
                def factory(out_dir, device):
                    made.append(1)
                    return rec
                yield SourcePanel(self._loader, state=self._state, recorder_factory=factory)

        app = _H()
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.start_record()
            panel.start_record()
            await pilot.pause()
            self.assertEqual(made, [1])
            self.assertTrue(panel.recording)
            self.assertFalse(rec.stopped)

    async def test_a_take_with_signal_is_loaded_as_the_source(self):
        """The whole point: a recording becomes the source through the SAME pipeline a file
        takes, so beat detection / Run / the session checkpoint are untouched."""
        rec = FakeRecorder("/tmp", measurement=measurement(path="/tmp/rec/good.wav", rms=4000))
        app = _Host(recorder=rec)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.toggle_record()
            await pilot.pause()
            panel.toggle_record()
            await _settle(app, pilot)
            self.assertIsNotNone(app.loaded)
            self.assertEqual(app.loaded.audio_file_path, "/tmp/rec/good.wav")

    async def test_a_silent_take_is_kept_and_named_but_never_auto_loaded(self):
        """A muted / unplugged / already-held mic yields a well-formed wav full of zeros.
        Auto-loading it puts the operator in front of a Run that can only make silence, and they
        blame the grinder. Loud, and not loaded."""
        rec = FakeRecorder("/tmp", measurement=measurement(path="/tmp/rec/dead.wav",
                                                          silent=True, rms=1))
        app = _Host(recorder=rec)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.toggle_record()
            await pilot.pause()
            panel.toggle_record()
            await _settle(app, pilot)
            self.assertIsNone(app.loaded, "a silent take must not become the source")
            self.assertIn("SILENT", panel.status_text)
            self.assertIn("/tmp/rec/dead.wav", panel.status_text)   # kept, and named
            # TakeRefused, NOT Failed — Failed means "no source is loaded" and would throw away a
            # file the operator had already loaded before reaching for the mic.
            self.assertIn("SILENT", app.refused)
            self.assertIsNone(app.failed)

    async def test_a_silent_take_names_the_process_holding_the_card(self):
        """On this node that contender is real — mesh-overhear holds the USB mic through raw
        ALSA, so 'the mic is broken' and 'something else already has it' must not read alike."""
        m = measurement(silent=True, rms=0)
        m["holders"] = [{"pid": 4242, "device": "pcmC0D0c",
                         "command": "arecord -D plughw:CARD=Camera,DEV=0"}]
        app = _Host(recorder=FakeRecorder("/tmp", measurement=m))
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.toggle_record()
            await pilot.pause()
            panel.toggle_record()
            await _settle(app, pilot)
            self.assertIn("4242", panel.status_text)

    async def test_a_too_short_take_is_not_loaded_either(self):
        rec = FakeRecorder("/tmp", measurement=measurement(too_short=True, duration=0.1))
        app = _Host(recorder=rec)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.toggle_record()
            await pilot.pause()
            panel.toggle_record()
            await _settle(app, pilot)
            self.assertIsNone(app.loaded)
            self.assertIn("TOO SHORT", panel.status_text)

    async def test_a_start_failure_says_so_instead_of_no_opping(self):
        """A RECORD press that does nothing and says nothing is indistinguishable from a
        recording in progress."""
        rec = FakeRecorder("/tmp", start_error=RuntimeError("no capture backend found"))
        app = _Host(recorder=rec)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.toggle_record()
            await _settle(app, pilot)
            self.assertFalse(panel.recording)
            self.assertIn("no capture backend", panel.status_text)
            self.assertIn("no capture backend", app.refused)
            self.assertIsNone(app.failed)

    async def test_a_stop_failure_reports_and_clears_the_recorder(self):
        rec = FakeRecorder("/tmp", stop_error=RuntimeError("wrote no audio"))
        app = _Host(recorder=rec)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel.toggle_record()
            await pilot.pause()
            panel.toggle_record()
            await _settle(app, pilot)
            self.assertFalse(panel.recording)
            self.assertIn("wrote no audio", panel.status_text)

    async def test_button_label_flips_to_stop_while_recording(self):
        rec = FakeRecorder("/tmp", measurement=measurement())
        app = _Host(recorder=rec)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            btn = app.query_one("#record_btn", Button)
            self.assertIn("REC", str(btn.label))
            panel.toggle_record()
            await pilot.pause()
            self.assertIn("STOP", str(btn.label))
            panel.toggle_record()
            await _settle(app, pilot)
            self.assertIn("REC", str(btn.label))

    async def test_record_refuses_while_a_source_load_is_in_flight(self):
        rec = FakeRecorder("/tmp", measurement=measurement())
        app = _Host(recorder=rec)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel._loading = True
            panel.toggle_record()
            await pilot.pause()
            self.assertFalse(rec.started)
            self.assertFalse(panel.recording)

    async def test_recordings_use_the_sessions_output_dir(self):
        captured = {}
        state = SessionState(output_dir="/tmp/gk-chosen-out")

        class _H(_Host):
            def compose(self):
                def factory(out_dir, device):
                    captured["out_dir"] = out_dir
                    captured["device"] = device
                    return FakeRecorder(out_dir, device, measurement=measurement())
                yield SourcePanel(self._loader, state=self._state, recorder_factory=factory)

        app = _H(state=state)
        async with app.run_test() as pilot:
            app.query_one(SourcePanel).toggle_record()
            await pilot.pause()
        self.assertEqual(captured["out_dir"], "/tmp/gk-chosen-out")
        self.assertIsNone(captured["device"])       # "auto" means: we did not pick


class RefusedTakeDoesNotDisturbTheLoadedSourceTest(unittest.IsolatedAsyncioTestCase):
    """A refused take is not a failed LOAD. The two used to share the ``Failed`` message, and the
    app's Failed handler clears ``state.cutter`` and disables Run — so pressing REC in a quiet
    room threw away the file you had already loaded."""

    def _app(self):
        from tui.app import GrainTUI
        return GrainTUI(output_dir="/tmp/gk-test-out", loader=lambda v, s=None: _FakeCutter(v),
                        player=lambda p: None, session_path="/tmp/gk-test-session2.json")

    async def _load_then_record(self, m):
        from tui.widgets.run_panel import RunPanel
        app = self._app()
        rec = FakeRecorder("/tmp", measurement=m)
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel._recorder_factory = lambda o, d: rec
            panel.load("/tmp/already-loaded.wav")
            await _settle(app, pilot)
            self.assertIsNotNone(app.state.cutter)
            panel.toggle_record()
            await pilot.pause()
            panel.toggle_record()
            await _settle(app, pilot)
            return app, panel, app.query_one(RunPanel)

    async def test_a_silent_take_leaves_the_loaded_source_alone(self):
        app, panel, run_panel = await self._load_then_record(measurement(silent=True, rms=1))
        self.assertIsNotNone(app.state.cutter, "a refused take threw away the loaded source")
        self.assertEqual(app.state.source_path, "/tmp/already-loaded.wav")
        self.assertIn("SILENT", panel.status_text)

    async def test_a_record_start_failure_leaves_the_loaded_source_alone(self):
        from tui.widgets.run_panel import RunPanel
        app = self._app()
        rec = FakeRecorder("/tmp", start_error=RuntimeError("no capture backend found"))
        async with app.run_test() as pilot:
            panel = app.query_one(SourcePanel)
            panel._recorder_factory = lambda o, d: rec
            panel.load("/tmp/already-loaded.wav")
            await _settle(app, pilot)
            panel.toggle_record()
            await _settle(app, pilot)
            self.assertIsNotNone(app.state.cutter)
            self.assertIn("no capture backend", panel.status_text)

    async def test_a_real_load_failure_still_clears_the_source(self):
        """The Failed path must keep working for what it is FOR — a gate that never fires is not
        a gate. A source that failed to load leaves nothing runnable behind."""
        from tui.app import GrainTUI

        def boom(v, s=None):
            raise ValueError("bad file")
        app = GrainTUI(output_dir="/tmp/gk-test-out", loader=boom, player=lambda p: None,
                       session_path="/tmp/gk-test-session3.json")
        async with app.run_test() as pilot:
            app.query_one(SourcePanel).load("/tmp/nope.wav")
            await _settle(app, pilot)
            self.assertIsNone(app.state.cutter)


class RecordAppWiringTest(unittest.IsolatedAsyncioTestCase):
    """The binding and the shutdown edge, on the REAL app rather than a host stub."""

    def _app(self, recorder):
        from tui.app import GrainTUI
        app = GrainTUI(output_dir="/tmp/gk-test-out", loader=lambda v, s=None: _FakeCutter(v),
                       player=lambda p: None, session_path="/tmp/gk-test-session.json")
        app._test_recorder = recorder
        return app

    async def test_ctrl_g_is_bound_to_record(self):
        app = self._app(None)
        keys = {b[0] if isinstance(b, tuple) else b.key for b in app.BINDINGS}
        self.assertIn("ctrl+g", keys)
        # ctrl+b would be swallowed by tmux (the prefix key) on every node this runs on.
        self.assertNotIn("ctrl+b", keys)

    async def test_action_record_reaches_the_panel(self):
        rec = FakeRecorder("/tmp", measurement=measurement())
        app = self._app(rec)
        async with app.run_test() as pilot:
            app.query_one(SourcePanel)._recorder_factory = lambda o, d: rec
            app.action_record()
            await pilot.pause()
            self.assertTrue(rec.started)
            app.action_record()
            await _settle(app, pilot)
            self.assertTrue(rec.stopped)

    async def test_an_in_flight_take_is_stopped_when_the_app_closes(self):
        """A backend orphaned by app exit holds a capture device open and locks the card for
        every other client on the node — which is exactly the stuck-arecord failure this node
        already lives with."""
        rec = FakeRecorder("/tmp", measurement=measurement())
        app = self._app(rec)
        async with app.run_test() as pilot:
            app.query_one(SourcePanel)._recorder_factory = lambda o, d: rec
            app.action_record()
            await pilot.pause()
            self.assertTrue(rec.recording)
        self.assertTrue(rec.stopped, "the app exited with a capture device still open")


class DeviceOptionsTest(unittest.TestCase):

    def test_auto_is_first_and_monitors_are_labelled_as_playback(self):
        """A monitor records what the node is PLAYING. Legitimate, but it must never be mistaken
        for a mic — so the label says which it is, and 'auto' stays the default."""
        import tui.widgets.source_panel as sp
        real = sp.mic.list_devices
        sp.mic.list_devices = lambda: [{"id": "in.mic", "name": "in.mic", "monitor": False},
                                       {"id": "out.monitor", "name": "out.monitor", "monitor": True}]
        try:
            opts = SourcePanel(lambda v: None)._device_options()
        finally:
            sp.mic.list_devices = real
        self.assertEqual(opts[0][1], "auto")
        self.assertEqual([o[1] for o in opts], ["auto", "in.mic", "out.monitor"])
        self.assertIn("plays", [o[0] for o in opts][2])

    def test_a_device_probe_failure_still_yields_auto(self):
        """The picker degrades to 'auto' rather than raising into compose() — but 'auto' is a
        real choice (let the backend pick), not a fabricated device."""
        import tui.widgets.source_panel as sp
        real = sp.mic.list_devices

        def boom():
            raise OSError("no audio server")
        sp.mic.list_devices = boom
        try:
            opts = SourcePanel(lambda v: None)._device_options()
        finally:
            sp.mic.list_devices = real
        self.assertEqual(opts, [("auto (default input)", "auto")])


if __name__ == "__main__":
    unittest.main()
