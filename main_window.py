import os
from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QPushButton, QWidget, 
                               QFileDialog, QMessageBox, QInputDialog)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtCore import QUrl

from automixer_config_panel import AutoMixerConfigPanel
from cutter.sample_cut_tool import SampleCutter
from workers import YouTubeDownloaderWorker
from help_dialog import HelpDialog

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Granular Sampler")
        self.setGeometry(100, 100, 800, 600)

        self.setup_ui()

        self.sample_cutter = None
        self.automixer_panel = None
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.add_button("Load Audio from File", self.load_audio_from_file, "Click to select an audio file from your computer")
        self.add_button("Load Audio from YouTube", self.load_audio_from_youtube, "Click to enter a YouTube URL and download the audio")
        self.add_button("Play Original", lambda: self.play_audio(is_original=True), "Play the original, unprocessed audio")
        
        self.play_mixed_button = self.add_button("Play Mixed", lambda: self.play_audio(is_original=False), "Play the processed audio after running AutoMixer")
        self.play_mixed_button.setEnabled(False)
        
        self.save_button = self.add_button("Save Mixed Audio", self.save_mixed_audio, "Save the processed audio to a file")
        self.save_button.setEnabled(False)
        
        self.add_button("Help", self.show_help, "Click for instructions on how to use this application")

    def add_button(self, text, callback, tooltip):
        button = QPushButton(text)
        button.clicked.connect(callback)
        button.setToolTip(tooltip)
        self.layout.addWidget(button)
        return button

    def load_audio_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Audio File", "", "Audio Files (*.mp3 *.wav)")
        if file_name:
            self.load_audio(file_name)

    def load_audio_from_youtube(self):
        url, ok = QInputDialog.getText(self, "YouTube URL", "Enter the YouTube video URL:")
        if ok and url:
            self.youtube_downloader = YouTubeDownloaderWorker(url, "samples")
            self.youtube_downloader.finished.connect(self.on_youtube_download_finished)
            self.youtube_downloader.start()
            QMessageBox.information(self, "Download Started", "YouTube audio download has started. Please wait...")

    def on_youtube_download_finished(self, success, result):
        if success:
            self.load_audio(result)
        else:
            QMessageBox.critical(self, "Error", f"Failed to download YouTube audio: {result}")

    def load_audio(self, file_path):
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"The file {file_path} does not exist.")
            
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                raise ValueError(f"The file {file_path} is empty.")

            self.sample_cutter = SampleCutter(file_path, "samples")
            self.log_message(f"Loaded audio file: {file_path}")
            
            self.detected_sample_length = self.sample_cutter.sample_length
            
            self.create_automixer_panel()
            
            if self.automixer_panel:
                self.automixer_panel.set_detected_sample_length(self.detected_sample_length)
            
            if hasattr(self.sample_cutter, 'beats') and self.sample_cutter.beats.size > 0:
                self.log_message("Beat detection successful")
            else:
                self.handle_beat_detection_failure()
        except Exception as e:
            self.log_message(f"Error loading audio: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to load audio file: {str(e)}\n\nFile path: {file_path}\nFile size: {file_size} bytes")

    def play_audio(self, is_original=True):
        if self.sample_cutter:
            try:
                audio_file = self.sample_cutter.audio_file_path if is_original else self.sample_cutter.audio_file_path.replace(".mp3", "_mixed.mp3")
                if not os.path.exists(audio_file):
                    raise FileNotFoundError("Mixed audio file not found. Run AutoMixer first." if not is_original else "Original audio file not found.")
                
                self.player.setSource(QUrl.fromLocalFile(audio_file))
                self.player.play()
                self.log_message(f"Playing {'original' if is_original else 'mixed'} audio")
            except Exception as e:
                self.log_message(f"Error playing audio: {str(e)}")
                QMessageBox.critical(self, "Error", f"Failed to play audio: {str(e)}")

    def save_mixed_audio(self):
        if self.sample_cutter:
            try:
                source_file = self.sample_cutter.audio_file_path.replace(".mp3", "_mixed.mp3")
                if not os.path.exists(source_file):
                    raise FileNotFoundError("Mixed audio file not found. Run AutoMixer first.")
                
                save_path, _ = QFileDialog.getSaveFileName(self, "Save Mixed Audio", "", "Audio Files (*.mp3)")
                if save_path:
                    import shutil
                    shutil.copy2(source_file, save_path)
                    self.log_message(f"Mixed audio saved to: {save_path}")
                    QMessageBox.information(self, "Save Successful", f"Mixed audio saved to: {save_path}")
            except Exception as e:
                self.log_message(f"Error saving mixed audio: {str(e)}")
                QMessageBox.critical(self, "Error", f"Failed to save mixed audio: {str(e)}")

    def create_automixer_panel(self):
        if self.automixer_panel:
            self.layout.removeWidget(self.automixer_panel)
            self.automixer_panel.deleteLater()
        self.automixer_panel = AutoMixerConfigPanel(self.sample_cutter)
        self.layout.addWidget(self.automixer_panel)
        self.play_mixed_button.setEnabled(True)
        self.save_button.setEnabled(True)

    def log_message(self, message):
        if self.automixer_panel:
            self.automixer_panel.log_message(message)
        print(message)  # Also print to console for debugging

    def handle_beat_detection_failure(self):
        self.log_message("Beat detection failed. Using default sample length.")
        self.detected_sample_length = 1.0  # Default to 1 second
        if self.automixer_panel:
            self.automixer_panel.set_detected_sample_length(self.detected_sample_length)
        self.log_message(f"Default sample length set to {self.detected_sample_length:.2f} seconds")

    def show_help(self):
        help_dialog = HelpDialog(self)
        help_dialog.exec()
