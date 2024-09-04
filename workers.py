from PySide6.QtCore import QThread, Signal
from youtube_downloader import YoutubeDownloader

class YouTubeDownloaderWorker(QThread):
    finished = Signal(bool, str)
    progress = Signal(float)

    def __init__(self, url, destination_path):
        super().__init__()
        self.url = url
        self.destination_path = destination_path
        self.downloader = YoutubeDownloader()

    def run(self):
        self.downloader.progress.connect(self.progress.emit)
        result = self.downloader.download_video(self.url, self.destination_path)
        if result:
            self.finished.emit(True, result)
        else:
            self.finished.emit(False, "Download failed")

class AutoMixerWorker(QThread):
    finished = Signal(bool, str)
    progress = Signal(int)

    def __init__(self, sample_cutter):
        super().__init__()
        self.sample_cutter = sample_cutter

    def run(self):
        try:
            mixed_file = self.sample_cutter.automix("am")
            if mixed_file:
                self.finished.emit(True, f"AutoMixer process completed successfully! Mixed file: {mixed_file}")
            else:
                self.finished.emit(False, "AutoMixer process failed to produce a mixed file.")
        except Exception as e:
            self.finished.emit(False, str(e))
