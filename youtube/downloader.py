import yt_dlp
import os


def download_video(url, output_path, progress_callback=None):
    """Download a YouTube URL to an mp3 under <output_path>/downloads/ and return its path.

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
        raise RuntimeError(f"YouTube download failed: {e}") from e
    if not os.path.exists(final_filename):
        raise RuntimeError(f"download finished but no file at {final_filename}")
    return final_filename
