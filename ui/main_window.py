import os
from datetime import datetime
from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, 
                               QWidget, QPushButton, QFileDialog, QLabel, QTextEdit, 
                               QInputDialog, QApplication, QProgressBar,
                               QFormLayout, QDoubleSpinBox, QComboBox, QSpinBox, QCheckBox)
from PySide6.QtCore import QThread, Signal

from cutter.sample_cut_tool import SampleCutter
from automixer.runner import AutoMixerRunner
from youtube.downloader import download_video

class WorkerThread(QThread):
    progress = Signal(int)
    finished = Signal(str)

    def __init__(self, url, output_path):
        super().__init__()
        self.url = url
        self.output_path = output_path

    def run(self):
        try:
            file_path = download_video(self.url, self.output_path, self.progress.emit)
            if file_path and os.path.exists(file_path):
                self.finished.emit(file_path)
            else:
                self.finished.emit(f"Error: Downloaded file not found at {file_path}")
        except Exception as e:
            self.finished.emit(f"Error: {str(e)}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sample Cutter and AutoMixer")
        self.setGeometry(100, 100, 800, 600)

        self.setup_ui()

        self.sample_cutter = None
        self.audio_file_path = None

    def setup_ui(self):
        main_layout = QVBoxLayout()

        self.file_label = QLabel("No file selected")
        main_layout.addWidget(self.file_label)

        file_button_layout = QHBoxLayout()
        select_file_button = QPushButton("Select Audio File")
        select_file_button.clicked.connect(self.select_file)
        select_file_button.setToolTip("Choose an audio file from your computer")
        file_button_layout.addWidget(select_file_button)

        download_button = QPushButton("Download from YouTube")
        download_button.clicked.connect(self.download_from_youtube)
        download_button.setToolTip("Download audio from a YouTube video")
        file_button_layout.addWidget(download_button)

        main_layout.addLayout(file_button_layout)

        main_layout.addLayout(self.create_parameter_layout())

        automix_button = QPushButton("Run AutoMixer")
        automix_button.clicked.connect(self.run_automixer)
        automix_button.setToolTip("Start the AutoMixer process with the current parameters")
        main_layout.addWidget(automix_button)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        main_layout.addWidget(self.output_text)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

    def create_parameter_layout(self):
        param_layout = QFormLayout()
        
        self.speed_input = QDoubleSpinBox()
        self.speed_input.setRange(0.1, 2.0)
        self.speed_input.setSingleStep(0.1)
        self.speed_input.setValue(1.0)
        param_layout.addRow("Playback Speed (s):", self.speed_input)
        
        self.sample_speed_input = QDoubleSpinBox()
        self.sample_speed_input.setRange(0.1, 2.0)
        self.sample_speed_input.setSingleStep(0.1)
        self.sample_speed_input.setValue(1.0)
        param_layout.addRow("Sample Speed (ss):", self.sample_speed_input)
        
        self.sample_length_spin = QDoubleSpinBox()
        self.sample_length_spin.setRange(0.1, 10.0)
        self.sample_length_spin.setSingleStep(0.1)
        self.sample_length_spin.setDecimals(2)
        self.sample_length_spin.setValue(1.0)
        param_layout.addRow("Sample Length (l):", self.sample_length_spin)
        
        self.mode_input = QComboBox()
        self.mode_input.addItems(["r", "3", "3w"])
        param_layout.addRow("Mode (m):", self.mode_input)
        
        self.window_divider_input = QSpinBox()
        self.window_divider_input.setRange(1, 10)
        self.window_divider_input.setValue(2)
        param_layout.addRow("Window Divider:", self.window_divider_input)
        
        self.verbose_mode_checkbox = QCheckBox("Verbose Mode")
        param_layout.addRow(self.verbose_mode_checkbox)

        return param_layout

    def select_file(self):
        self.audio_file_path, _ = QFileDialog.getOpenFileName(self, "Select Audio File", "", "Audio Files (*.mp3 *.wav *.webm *.m4a)")
        
        if self.audio_file_path:
            self.file_label.setText(f"Selected file: {self.audio_file_path}")
            self.log_message(f"Loaded file: {self.audio_file_path}")
            self.log_message("Detecting beats...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate progress
            QApplication.processEvents()  # Force GUI update
            
            try:
                self.sample_cutter = SampleCutter(self.audio_file_path, "samples")
                self.sample_cutter._detect_beats()
                if hasattr(self.sample_cutter, 'beats') and self.sample_cutter.beats:
                    avg_beat_length = sum(b[1] - b[0] for b in self.sample_cutter.beats[1:]) / (len(self.sample_cutter.beats) - 1)
                    self.detected_sample_length = avg_beat_length / 1000  # Convert to seconds
                    self.log_message(f"Beats detected. Suggested sample length: {self.detected_sample_length:.2f} seconds")
                    self.sample_length_spin.setValue(self.detected_sample_length)
                else:
                    self.log_message("Beats detected, but no sample length could be calculated.")
                    self.handle_beat_detection_failure()
            except Exception as e:
                self.log_message(f"Error detecting beats: {str(e)}")
                self.handle_beat_detection_failure()
            finally:
                self.progress_bar.setVisible(False)

    def handle_beat_detection_failure(self):
        self.log_message("Beat detection failed. Using default sample length.")
        self.detected_sample_length = 1.0  # Default to 1 second
        self.sample_length_spin.setValue(self.detected_sample_length)
        self.log_message(f"Default sample length set to {self.detected_sample_length:.2f} seconds")

    def download_from_youtube(self):
        url, ok = QInputDialog.getText(self, "YouTube Downloader", "Enter YouTube URL:")
        if ok and url:
            self.log_message(f"Downloading from YouTube: {url}")
            self.progress_bar.setVisible(True)
            self.worker = WorkerThread(url, ".")
            self.worker.progress.connect(self.update_progress)
            self.worker.finished.connect(self.download_finished)
            self.worker.start()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def download_finished(self, result):
        self.progress_bar.setVisible(False)
        if isinstance(result, str) and result.startswith("Error"):
            self.log_message(f"Error downloading: {result}")
        elif isinstance(result, str) and os.path.exists(result):
            self.log_message(f"Download complete: {result}")
            self.audio_file_path = result
            self.file_label.setText(f"Selected file: {result}")
            self.log_message("File downloaded successfully. You can now select it to detect beats.")
            self.select_file()  # Automatically start beat detection
        else:
            self.log_message(f"Error: Invalid download result. Expected file path, got: {result}")

    def update_config_display(self):
        if self.sample_cutter:
            config = self.sample_cutter.config
            config_text = f"""
AutoMixer config:
Audio: {config.audio}
Beats: {len(config.beats) if config.beats else 'Not detected'}
Mode: {config.mode}
Speed: {config.speed}
Sample Length: {config.sample_length}
Sample Speed: {config.sample_speed}
Verbose Mode Enabled: {config.is_verbose_mode_enabled}
Window Divider: {config.window_divider}
"""
            self.log_message(config_text)
        else:
            self.log_message("No configuration available. Please select an audio file first.")

    def run_automixer(self):
        if not self.audio_file_path:
            self.log_message("Please select an audio file first")
            return

        if not self.sample_cutter or not hasattr(self.sample_cutter, 'beats'):
            self.log_message("Beats not detected. Please load the audio file and detect beats first.")
            return

        self.update_config()

        runner = AutoMixerRunner()
        try:
            mix = runner.run(self.sample_cutter.config)
            output_file = f"{os.path.splitext(os.path.basename(self.audio_file_path))[0]}___mix_cut{int(float(self.sample_cutter.config.sample_length)*1000)}-vtgsmlpr____" + \
                          f"{datetime.now().strftime('%Y_%m_%d_%H%M')}.mp3"
            mix.export(output_file, format="mp3")
            self.log_message(f"AutoMixer completed. Output saved as {output_file}")
        except Exception as e:
            self.log_message(f"Error running AutoMixer: {str(e)}")

    def update_config(self):
        if self.sample_cutter:
            self.sample_cutter.config.speed = self.speed_input.value()
            self.sample_cutter.config.sample_speed = self.sample_speed_input.value()
            self.sample_cutter.config.sample_length = self.sample_length_spin.value()
            self.sample_cutter.config.mode = self.mode_input.currentText()
            self.sample_cutter.config.window_divider = self.window_divider_input.value()
            self.sample_cutter.config.is_verbose_mode_enabled = self.verbose_mode_checkbox.isChecked()

    def log_message(self, message):
        self.output_text.append(message)
