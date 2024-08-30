import yt_dlp
import os

# Enter the YouTube video URL
url = "https://www.youtube.com/watch?v=k_bkjsjElrI"


def download_video(url, output_path):
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
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
        file_name = ydl.prepare_filename(ydl.extract_info(url, download=True))
        return os.path.splitext(file_name)[0] + ".mp3"
