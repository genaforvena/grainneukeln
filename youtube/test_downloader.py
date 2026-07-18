import unittest
from unittest import mock

import youtube.downloader as downloader


class DownloaderErrorTest(unittest.TestCase):
    def test_raises_instead_of_returning_error_string(self):
        # Regression: it used to return "Error: …" which then got fed to SampleCutter as a path and
        # surfaced as a misleading "File does not exist". A failed download must RAISE.
        with mock.patch.object(downloader, "yt_dlp") as ydl:
            ydl.YoutubeDL.side_effect = RuntimeError("network down")
            with self.assertRaises(RuntimeError) as cm:
                downloader.download_video("https://youtube.com/x", "/tmp/gnk")
            self.assertIn("network down", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
