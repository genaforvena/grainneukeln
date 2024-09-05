import os
import yt_dlp
from PySide6.QtCore import QObject, Signal
from concurrent.futures import ThreadPoolExecutor, TimeoutError

class YoutubeDownloader(QObject):
    progress = Signal(float)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self):
        super().__init__()

    def download_video(self, url, destination_path):
        with ThreadPoolExecutor() as executor:
            future = executor.submit(self._download, url, destination_path)
            try:
                output_file = future.result(timeout=300)  # 5 minutes timeout
                self.finished.emit(output_file)
                return output_file
            except TimeoutError:
                self.error.emit("Download timed out after 5 minutes")
                return None
            except Exception as e:
                self.error.emit(f"Error: {str(e)}")
                return None

    def _download(self, url, destination_path):
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
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            output_file = os.path.splitext(filename)[0] + '.mp3'
        return output_file

    def _progress_hook(self, d):
        if d['status'] == 'downloading':
            p = d['_percent_str']
            p = p.replace('%','')
            self.progress.emit(float(p))
        elif d['status'] == 'finished':
            self.progress.emit(100)
