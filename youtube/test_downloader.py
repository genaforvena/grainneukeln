import unittest
from unittest import mock

import youtube.downloader as downloader


def _fake_ydl(prepared_name):
    """A yt_dlp stand-in whose context manager yields a YoutubeDL that "downloads" successfully.

    Returns (module_mock, calls) where calls records every URL handed to extract_info.
    """
    calls = []
    inst = mock.MagicMock()

    def extract_info(url, download=True):
        calls.append(url)
        return {"title": "t"}

    inst.extract_info.side_effect = extract_info
    inst.prepare_filename.return_value = prepared_name
    mod = mock.MagicMock()
    mod.YoutubeDL.return_value.__enter__.return_value = inst
    return mod, calls


class DownloaderErrorTest(unittest.TestCase):
    def test_raises_instead_of_returning_error_string(self):
        # Regression: it used to return "Error: …" which then got fed to SampleCutter as a path and
        # surfaced as a misleading "File does not exist". A failed download must RAISE.
        with mock.patch.object(downloader, "yt_dlp") as ydl:
            ydl.YoutubeDL.side_effect = RuntimeError("network down")
            with self.assertRaises(RuntimeError) as cm:
                downloader.download_video("https://youtube.com/x", "/tmp/gnk")
            self.assertIn("network down", str(cm.exception))

    def test_failure_message_names_the_actual_host(self):
        # A SoundCloud failure reported as "YouTube download failed" sends the reader to the wrong
        # service. The message must name the host that was actually contacted.
        with mock.patch.object(downloader, "yt_dlp") as ydl:
            ydl.YoutubeDL.side_effect = RuntimeError("404")
            with self.assertRaises(RuntimeError) as cm:
                downloader.download_video("https://soundcloud.com/a/b", "/tmp/gnk")
            msg = str(cm.exception)
            self.assertIn("soundcloud.com", msg)
            self.assertNotIn("YouTube", msg)


class ProviderAgnosticTest(unittest.TestCase):
    """The downloader must hand ANY http(s) URL to yt_dlp verbatim.

    The operator's own tracks live on SoundCloud. Nothing in this module may gate on the host —
    a YouTube-only allowlist (or a "normalize to a watch URL" step) would silently sever every
    non-YouTube source. These go RED the moment such a guard is added.
    """

    HOSTS = [
        "https://soundcloud.com/salamaaashop/obscura-dub",
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123",
        "https://artist.bandcamp.com/track/x",
        "https://vimeo.com/12345",
    ]

    def test_every_host_reaches_yt_dlp_unmodified(self):
        for url in self.HOSTS:
            with self.subTest(url=url):
                mod, calls = _fake_ydl("/tmp/gnk/downloads/t.m4a")
                with mock.patch.object(downloader, "yt_dlp", mod), \
                        mock.patch.object(downloader.os.path, "exists", return_value=True):
                    downloader.download_video(url, "/tmp/gnk")
                self.assertEqual(calls, [url],
                                 f"{url} was rewritten or rejected before reaching yt_dlp")

    def test_soundcloud_hls_m4a_is_returned_as_the_mp3_the_postprocessor_writes(self):
        # SoundCloud delivers HLS; prepare_filename reports the pre-postprocessor container
        # (.m4a), while FFmpegExtractAudio writes .mp3. Returning the .m4a would hand SampleCutter
        # a path that does not exist.
        mod, _ = _fake_ydl("/tmp/gnk/downloads/obscura dub.m4a")
        with mock.patch.object(downloader, "yt_dlp", mod), \
                mock.patch.object(downloader.os.path, "exists", return_value=True):
            out = downloader.download_video(
                "https://soundcloud.com/salamaaashop/obscura-dub", "/tmp/gnk")
        self.assertEqual(out, "/tmp/gnk/downloads/obscura dub.mp3")

    def test_postprocessor_is_configured_for_mp3(self):
        # The mp3 the return value promises is produced by this postprocessor. If it is ever
        # dropped, the returned path stops existing for every provider at once.
        mod, _ = _fake_ydl("/tmp/gnk/downloads/t.m4a")
        with mock.patch.object(downloader, "yt_dlp", mod), \
                mock.patch.object(downloader.os.path, "exists", return_value=True):
            downloader.download_video("https://soundcloud.com/a/b", "/tmp/gnk")
        opts = mod.YoutubeDL.call_args[0][0]
        self.assertEqual(opts["postprocessors"][0]["preferredcodec"], "mp3")
        self.assertTrue(opts["noplaylist"], "a SoundCloud /sets/ link must not pull the whole set")


if __name__ == "__main__":
    unittest.main()
