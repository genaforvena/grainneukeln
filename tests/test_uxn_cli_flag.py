import os
import subprocess
import sys
import tempfile
import unittest

from pydub import AudioSegment

ROOT = os.path.join(os.path.dirname(__file__), "..")
FULL_ASSET = os.path.join(ROOT, "assets", "test_audio.mp3")


class UxnFeedbackFlagTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The repo's own O(n^2)-mixer convention (cutter/test_series_cli.py, tui/test_engine.py)
        # truncates audio in-process after SampleCutter loads it. A subprocess-level CLI smoke
        # test has no such post-load hook -- main.py always renders the file it's given -- so a
        # full ~174s source (measured: a single tick's mixing pass did not finish in 5 minutes)
        # would blow any sane test budget. Truncate at the FILE level instead: write a short wav
        # (first 5s) and point the subprocess at that -- still a genuine end-to-end CLI run
        # (real argparse, real SampleCutter load + beat detection, real Uxn subprocess ticks),
        # just on material the O(n^2) mixer can actually finish inside the timeout.
        cls._tmpdir = tempfile.TemporaryDirectory()
        full = AudioSegment.from_mp3(FULL_ASSET)
        cls.asset = os.path.join(cls._tmpdir.name, "short.wav")
        full[:5000].export(cls.asset, format="wav")

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def test_uxn_feedback_flag_is_accepted_and_closes_the_loop(self):
        out_dir = "/tmp/grainneukeln_uxn_feedback_test"
        os.makedirs(out_dir, exist_ok=True)
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "main.py"), self.asset, out_dir,
             "--uxn-ctrl", "--uxn-ticks", "2", "--uxn-feedback"],
            capture_output=True, text=True, timeout=90, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[uxn tick 0]", result.stdout)
        self.assertIn("[uxn tick 1]", result.stdout)


if __name__ == "__main__":
    unittest.main()
