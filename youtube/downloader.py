import yt_dlp
import os

# Enter the YouTube video URL
url = "https://www.youtube.com/watch?v=k_bkjsjElrI"


def download_video(url, output_path, progress_callback=None):
    def progress_hook(d):
        if d['status'] == 'downloading' and progress_callback:
            try:
                percent = d.get('_percent_str', '0%').replace('%', '')
                progress_callback(int(float(percent)))
            except ValueError:
                pass  # Ignore if we can't convert the percentage to a number

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
            if os.path.exists(final_filename):
                return final_filename
            else:
                return f"Error: File not found after download: {final_filename}"
    except Exception as e:
        return f"Error: {str(e)}"
