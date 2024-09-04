import os
import yt_dlp
from PySide6.QtCore import QObject, Signal

class YoutubeDownloader(QObject):
    progress = Signal(float)
    finished = Signal(str)

    def __init__(self):
        super().__init__()

    def download_video(self, url, destination_path):
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': os.path.join(destination_path, '%(title)s.%(ext)s'),
            'progress_hooks': [self._progress_hook],
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                output_file = os.path.splitext(filename)[0] + '.mp3'
                self.finished.emit(output_file)
                return output_file
        except Exception as e:
            self.finished.emit(f"Error: {str(e)}")
            return None

    def _progress_hook(self, d):
        if d['status'] == 'downloading':
            p = d['_percent_str']
            p = p.replace('%','')
            self.progress.emit(float(p))
        elif d['status'] == 'finished':
            self.progress.emit(100)
