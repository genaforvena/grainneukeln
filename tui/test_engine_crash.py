"""Crash-cause logging contract (operator 2026-07-19: 'let it crash, but record what caused it —
what setting'). The engine must append the recipe + source + traceback to CRASH_LOG before
re-raising, so a process-killing OOM or segfault still leaves a 'what setting caused it' record."""
import os
import tempfile
import unittest
from unittest import mock

from tui import engine


def _boom_config():
    """A minimal AutoMixerConfig the recipe formatter can read."""
    from automixer.config import AutoMixerConfig
    from pydub import AudioSegment
    audio = AudioSegment.silent(duration=100)
    import numpy as np
    beats = np.array([0, 50], dtype=int)
    return AutoMixerConfig(
        audio=audio, beats=beats, sample_length=160, mode="rw", speed=2.0,
        sample_speed=0.75, window_divider=4, seed=7,
    )


class CrashLoggerTest(unittest.TestCase):
    def test_record_crash_appends_recipe_source_and_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            log = os.path.join(td, "crash.log")
            with mock.patch("tui.engine.CRASH_LOG", log):
                cfg = _boom_config()
                try:
                    raise RuntimeError("synthetic boom")
                except RuntimeError as e:
                    engine._record_crash(cfg, "/tmp/src.wav", type(e), e, e.__traceback__)
                with open(log) as f:
                    text = f.read()
            self.assertIn("CRASH", text)
            self.assertIn("recipe:", text)
            self.assertIn("m-rw", text)
            self.assertIn("l160", text)
            self.assertIn("w4", text)
            self.assertIn("ss0.75", text)
            self.assertIn("s2.0", text)
            self.assertIn("seed7", text)
            self.assertIn("source: /tmp/src.wav", text)
            self.assertIn("RuntimeError: synthetic boom", text)
            self.assertIn("traceback:", text)

    def test_record_crash_append_only_keeps_history(self):
        """Two crashes leave BOTH records — the operator scans the recent few for a pattern."""
        with tempfile.TemporaryDirectory() as td:
            log = os.path.join(td, "crash.log")
            with mock.patch("tui.engine.CRASH_LOG", log):
                cfg = _boom_config()
                for msg in ("first", "second"):
                    try:
                        raise RuntimeError(msg)
                    except RuntimeError as e:
                        engine._record_crash(cfg, "/x.wav", type(e), e, e.__traceback__)
                with open(log) as f:
                    text = f.read()
            self.assertEqual(text.count("CRASH"), 2)
            self.assertIn("first", text)
            self.assertIn("second", text)

    def test_record_crash_write_failure_is_swallowed(self):
        """A bad CRASH_LOG path must NOT mask the original exception being recorded. The recorder
        is a side-channel — its failure is silent, the caller's exception still propagates."""
        with mock.patch("tui.engine.CRASH_LOG", "/no/such/dir/crash.log"):
            cfg = _boom_config()
            try:
                raise ValueError("orig")
            except ValueError as e:
                engine._record_crash(cfg, "/x", type(e), e, e.__traceback__)  # must not raise

    def test_engine_run_logs_and_reraises_on_exception(self):
        """The full run() path: when AutoMixerRunner.run raises, engine.run MUST append to the crash
        log AND re-raise — never swallow. The TUI's worker thread needs the real exception."""
        with tempfile.TemporaryDirectory() as td:
            log = os.path.join(td, "crash.log")
            out = os.path.join(td, "out")
            with mock.patch("tui.engine.CRASH_LOG", log), \
                 mock.patch("tui.engine.AutoMixerRunner") as Runner:
                Runner.return_value.run.side_effect = MemoryError("synthetic OOM")
                cfg = _boom_config()
                with self.assertRaises(MemoryError):
                    engine.run(cfg, out, source_path="/tmp/src.wav")
                self.assertTrue(os.path.exists(log))
                with open(log) as f:
                    text = f.read()
                self.assertIn("MemoryError", text)
                self.assertIn("recipe:", text)
                self.assertIn("source: /tmp/src.wav", text)

    def test_engine_run_no_log_on_success(self):
        """A clean grind writes nothing to the crash log — only failures record."""
        with tempfile.TemporaryDirectory() as td:
            log = os.path.join(td, "crash.log")
            out = os.path.join(td, "out")
            with mock.patch("tui.engine.CRASH_LOG", log), \
                 mock.patch("tui.engine.AutoMixerRunner") as Runner:
                # A real AudioSegment-returning mock so export succeeds.
                from pydub import AudioSegment
                Runner.return_value.run.return_value = AudioSegment.silent(duration=100)
                cfg = _boom_config()
                engine.run(cfg, out, source_path="/tmp/x.wav")
            self.assertFalse(os.path.exists(log), "clean grind must not write a crash record")


class RecipeFormatterTest(unittest.TestCase):
    def test_recipe_format_matches_amc_string_idiom(self):
        """The recipe line must read like the amc string the operator already knows from the CLI
        (m-rw l160 w4 ss0.75 s2.0 c... k.. n..) so they recognize it instantly in the crash log."""
        from automixer.config import AutoMixerConfig, ChannelConfig
        from pydub import AudioSegment
        import numpy as np
        cfg = AutoMixerConfig(
            audio=AudioSegment.silent(duration=100),
            beats=np.array([0, 50], dtype=int),
            sample_length=160, mode="rw", speed=2.0, sample_speed=0.75, window_divider=4,
            channels_config=[ChannelConfig(100, 8000)], seed=11,
        )
        recipe = engine._config_to_recipe(cfg)
        self.assertEqual(recipe, "m-rw l160 w4 ss0.75 s2.0 c100-8000 seed11")


if __name__ == "__main__":
    unittest.main()
