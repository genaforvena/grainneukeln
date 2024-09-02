import sys
import os
import traceback
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                               QPushButton, QFileDialog, QWidget, QLabel, QComboBox, 
                               QDoubleSpinBox, QSpinBox, QGroupBox, QLineEdit, QMessageBox,
                               QProgressBar, QPlainTextEdit, QToolTip, QInputDialog)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtCore import QUrl
from PySide6.QtGui import QFont

from cutter.sample_cut_tool import SampleCutter
import youtube.downloader as youtube_downloader

class HelpDialog(QMessageBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("How to Use")
        self.setText("Granular Sampler and AutoMixer Instructions")
        self.setInformativeText(
            "1. Load Audio: Click 'Load Audio' to select a file or enter a YouTube URL.\n"
            "2. Configure AutoMixer: Adjust settings in the AutoMixer panel.\n"
            "3. Apply Configuration: Click 'Apply Configuration' to set your changes.\n"
            "4. Run AutoMixer: Click 'Run AutoMixer' to process your audio.\n"
            "5. Preview: Use 'Play Original' and 'Play Mixed' to hear results.\n"
            "6. Save: Click 'Save Mixed Audio' to export your processed audio.\n\n"
            "Hover over elements for more detailed information!"
        )
        self.setIcon(QMessageBox.Information)

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
            downloaded_file = youtube_downloader.download_video(self.url, self.destination_path)
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
            
            self.sample_cutter.automix("am")
            self.finished.emit(True, "AutoMixer process completed successfully!")
        except Exception as e:
            self.finished.emit(False, str(e))

class AutoMixerConfigPanel(QGroupBox):
    def __init__(self, sample_cutter):
        super().__init__("AutoMixer Configuration")
        self.sample_cutter = sample_cutter
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Mode selection
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["rw"])  # Add more modes as needed
        self.mode_combo.setToolTip("Select the AutoMixer mode")
        mode_layout.addWidget(self.mode_combo)
        layout.addLayout(mode_layout)

        # Speed configuration
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("Speed:"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 10.0)
        self.speed_spin.setSingleStep(0.1)
        self.speed_spin.setValue(1.0)
        self.speed_spin.setToolTip("Set the overall speed of the mixed audio")
        speed_layout.addWidget(self.speed_spin)
        layout.addLayout(speed_layout)

        # Sample speed configuration
        sample_speed_layout = QHBoxLayout()
        sample_speed_layout.addWidget(QLabel("Sample Speed:"))
        self.sample_speed_spin = QDoubleSpinBox()
        self.sample_speed_spin.setRange(0.1, 10.0)
        self.sample_speed_spin.setSingleStep(0.1)
        self.sample_speed_spin.setValue(1.0)
        self.sample_speed_spin.setToolTip("Set the speed of individual samples")
        sample_speed_layout.addWidget(self.sample_speed_spin)
        layout.addLayout(sample_speed_layout)

        # Window divider configuration
        window_layout = QHBoxLayout()
        window_layout.addWidget(QLabel("Window Divider:"))
        self.window_spin = QSpinBox()
        self.window_spin.setRange(1, 10)
        self.window_spin.setValue(2)
        self.window_spin.setToolTip("Set the window divider for sample selection")
        window_layout.addWidget(self.window_spin)
        layout.addLayout(window_layout)

        # Channel configuration
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Channels:"))
        self.channel_edit = QLineEdit("0,15000")
        self.channel_edit.setPlaceholderText("e.g., 0,15000")
        self.channel_edit.setToolTip("Set the frequency range for channels (low,high)")
        channel_layout.addWidget(self.channel_edit)
        layout.addLayout(channel_layout)

        # Sample length configuration
        length_layout = QHBoxLayout()
        length_layout.addWidget(QLabel("Sample Length:"))
        self.length_edit = QLineEdit()
        self.length_edit.setPlaceholderText("e.g., 1000 (in ms)")
        self.length_edit.setToolTip("Set the length of each sample in milliseconds")
        length_layout.addWidget(self.length_edit)
        layout.addLayout(length_layout)

        # Apply button
        self.apply_button = QPushButton("Apply Configuration")
        self.apply_button.clicked.connect(self.apply_config)
        self.apply_button.setToolTip("Apply the current configuration settings")
        layout.addWidget(self.apply_button)

        # Run AutoMixer button
        self.run_button = QPushButton("Run AutoMixer")
        self.run_button.clicked.connect(self.run_automixer)
        self.run_button.setToolTip("Start the AutoMixer process with current settings")
        layout.addWidget(self.run_button)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setToolTip("Shows the progress of the AutoMixer process")
        layout.addWidget(self.progress_bar)

        # Log display
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setToolTip("Displays logs and messages from the application")
        layout.addWidget(self.log_display)

        self.setLayout(layout)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Granular Sampler")
        self.setGeometry(100, 100, 800, 600)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.load_button = QPushButton("Load Audio from File")
        self.load_button.clicked.connect(self.load_audio_from_file)
        self.load_button.setToolTip("Click to select an audio file from your computer")
        self.layout.addWidget(self.load_button)

        self.load_youtube_button = QPushButton("Load Audio from YouTube")
        self.load_youtube_button.clicked.connect(self.load_audio_from_youtube)
        self.load_youtube_button.setToolTip("Click to enter a YouTube URL and download the audio")
        self.layout.addWidget(self.load_youtube_button)

        self.play_button = QPushButton("Play Original")
        self.play_button.clicked.connect(lambda: self.play_audio(is_original=True))
        self.play_button.setToolTip("Play the original, unprocessed audio")
        self.layout.addWidget(self.play_button)

        self.play_mixed_button = QPushButton("Play Mixed")
        self.play_mixed_button.clicked.connect(lambda: self.play_audio(is_original=False))
        self.play_mixed_button.setToolTip("Play the processed audio after running AutoMixer")
        self.layout.addWidget(self.play_mixed_button)
        self.play_mixed_button.setEnabled(False)

        self.save_button = QPushButton("Save Mixed Audio")
        self.save_button.clicked.connect(self.save_mixed_audio)
        self.save_button.setToolTip("Save the processed audio to a file")
        self.layout.addWidget(self.save_button)
        self.save_button.setEnabled(False)

        self.help_button = QPushButton("Help")
        self.help_button.clicked.connect(self.show_help)
        self.help_button.setToolTip("Click for instructions on how to use this application")
        self.layout.addWidget(self.help_button)

        self.sample_cutter = None
        self.automixer_panel = None
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

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
            self.sample_cutter = SampleCutter(file_path, "samples")
            self.log_message(f"Loaded audio file: {file_path}")
            self.create_automixer_panel()
        except Exception as e:
            self.log_message(f"Error loading audio: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to load audio file: {str(e)}")

    def play_audio(self, is_original=True):
        if self.sample_cutter:
            try:
                if is_original:
                    audio_file = self.sample_cutter.audio_file_path
                else:
                    # Assuming the mixed file is saved with a "_mixed" suffix
                    audio_file = self.sample_cutter.audio_file_path.replace(".mp3", "_mixed.mp3")
                    if not os.path.exists(audio_file):
                        raise FileNotFoundError("Mixed audio file not found. Run AutoMixer first.")
                
                self.player.setSource(QUrl.fromLocalFile(audio_file))
                self.player.play()
                self.log_message(f"Playing {'original' if is_original else 'mixed'} audio")
            except Exception as e:
                self.log_message(f"Error playing audio: {str(e)}")
                QMessageBox.critical(self, "Error", f"Failed to play audio: {str(e)}")

    def save_mixed_audio(self):
        if self.sample_cutter:
            try:
                # Assuming the mixed file is saved with a "_mixed" suffix
                source_file = self.sample_cutter.audio_file_path.replace(".mp3", "_mixed.mp3")
                if not os.path.exists(source_file):
                    raise FileNotFoundError("Mixed audio file not found. Run AutoMixer first.")
                
                save_path, _ = QFileDialog.getSaveFileName(self, "Save Mixed Audio", "", "Audio Files (*.mp3)")
                if save_path:
                    # Copy the file to the new location
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

    def show_help(self):
        help_dialog = HelpDialog(self)
        help_dialog.exec()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set global tooltip style
    QToolTip.setFont(QFont('SansSerif', 10))
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
