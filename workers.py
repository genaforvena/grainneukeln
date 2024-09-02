from PySide6.QtCore import QThread, Signal
from youtube_downloader import YoutubeDownloader

class YouTubeDownloaderWorker(QThread):
    finished = Signal(bool, str)
    progress = Signal(int)

    def __init__(self, url, destination_path):
        super().__init__()
        self.url = url
        self.destination_path = destination_path

    def run(self):
        try:
            # Download video
            downloaded_file = YoutubeDownloader.download_video(self.url, self.destination_path)
            self.finished.emit(True, downloaded_file)
        except Exception as e:
            self.finished.emit(False, str(e))

class AutoMixerWorker(QThread):
    finished = Signal(bool, str)
    progress = Signal(int)

    def __init__(self, sample_cutter):
        super().__init__()
        self.sample_cutter = sample_cutter

    def run(self):
        try:
            # Simulating progress for demonstration
            for i in range(101):
                self.progress.emit(i)
                self.msleep(50)  # Adjust sleep time based on actual processing time
            
            mixed_file = self.sample_cutter.automix("am")
            if mixed_file:
                self.finished.emit(True, f"AutoMixer process completed successfully! Mixed file: {mixed_file}")
            else:
                self.finished.emit(False, "AutoMixer process failed to produce a mixed file.")
        except Exception as e:
            self.finished.emit(False, str(e))
