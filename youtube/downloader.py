import yt_dlp
import os
from urllib.parse import urlparse


def download_video(url, output_path, progress_callback=None):
    """Download ANY yt_dlp-supported media URL to an mp3 under <output_path>/downloads/.

    Provider-agnostic by construction: the URL is handed to yt_dlp verbatim and its extractor
    registry picks the host. YouTube and **SoundCloud** are both first-class (SoundCloud arrives
    as an HLS m4a and is transcoded to mp3 by the same FFmpegExtractAudio postprocessor); Bandcamp,
    Vimeo, Mixcloud and the rest of yt_dlp's list work for free. Do NOT add a host allowlist here —
    the operator's own tracks live on SoundCloud, and a YouTube-only guard would silently sever
    them. ``test_downloader.py`` pins this.

    progress_callback, if given, is called with an integer 0..100 as the download proceeds.
    On any failure this RAISES RuntimeError (it used to return an "Error: …" string, which then got
    fed to SampleCutter as if it were a file path and surfaced as a bogus "File does not exist").
    """
    def progress_hook(d):
        if d.get("status") != "downloading" or not progress_callback:
            return
        # _percent_str carries ANSI colour codes and is unreliable — compute from bytes instead.
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        done = d.get("downloaded_bytes")
        if total and done is not None:
            try:
                progress_callback(int(done * 100 / total))
            except (ValueError, ZeroDivisionError):
                pass

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_path, "downloads", "%(title)s.%(ext)s"),
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "progress_hooks": [progress_hook],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            final_filename = os.path.splitext(filename)[0] + ".mp3"
    except Exception as e:
        # Name the HOST, not "YouTube" — a SoundCloud 404 reported as a "YouTube download failed"
        # sends the reader to the wrong service (an error message names a cause, not the cause).
        host = urlparse(url).netloc or "the source"
        raise RuntimeError(f"download from {host} failed: {e}") from e
    if not os.path.exists(final_filename):
        raise RuntimeError(f"download finished but no file at {final_filename}")
    return final_filename
