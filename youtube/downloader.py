import yt_dlp
import os

# Enter the YouTube video URL
url = "https://www.youtube.com/watch?v=k_bkjsjElrI"


def download_video(url, output_path, progress_callback=None):
    def progress_hook(d):
        if d['status'] == 'downloading':
            percent = d['_percent_str']
            percent = percent.replace('%', '')
            progress_callback(int(float(percent)))

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
        "progress_hooks": [progress_hook] if progress_callback else [],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
        file_name = ydl.prepare_filename(ydl.extract_info(url, download=True))
        return os.path.splitext(file_name)[0] + ".mp3"
