import os
from datetime import datetime
from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, 
                               QWidget, QPushButton, QFileDialog, QLabel, QTextEdit, 
                               QLineEdit, QToolTip, QInputDialog, QApplication, QProgressBar,
                               QFormLayout, QDoubleSpinBox, QComboBox)
from PySide6.QtCore import QThread, Signal

from cutter.sample_cut_tool import SampleCutter
from automixer.config import AutoMixerConfig
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

        # Custom parameter input
        # AutoMixer parameters
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
        
        self.length_input = QLineEdit()
        self.length_input.setPlaceholderText("e.g., /3 or *2")
        param_layout.addRow("Sample Length (l):", self.length_input)
        
        self.mode_input = QComboBox()
        self.mode_input.addItems(["r", "3", "3w"])
        param_layout.addRow("Mode (m):", self.mode_input)

        main_layout.addLayout(param_layout)

        # AutoMixer button
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

        self.sample_cutter = None
        self.audio_file_path = None

    def select_file(self):
        if not self.audio_file_path:
            self.audio_file_path, _ = QFileDialog.getOpenFileName(self, "Select Audio File", "", "Audio Files (*.mp3 *.wav *.webm *.m4a)")
        
        if self.audio_file_path:
            self.file_label.setText(f"Selected file: {self.audio_file_path}")
            self.output_text.append(f"Loaded file: {self.audio_file_path}")
            self.output_text.append("Detecting beats...")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate progress
            QApplication.processEvents()  # Force GUI update
            
            try:
                self.sample_cutter = SampleCutter(self.audio_file_path, "samples")
                self.sample_cutter._detect_beats()
                if hasattr(self.sample_cutter, 'beats') and self.sample_cutter.beats:
                    avg_beat_length = sum(b[1] - b[0] for b in self.sample_cutter.beats[1:]) / (len(self.sample_cutter.beats) - 1)
                    self.detected_sample_length = avg_beat_length / 1000  # Convert to seconds
                    self.output_text.append(f"Beats detected. Suggested sample length: {self.detected_sample_length:.2f} seconds")
                else:
                    self.output_text.append("Beats detected, but no sample length could be calculated.")
                    self.handle_beat_detection_failure()
            except ValueError as e:
                if "The truth value of an array with more than one element is ambiguous" in str(e):
                    self.output_text.append("Error: Beat detection failed due to ambiguous array values.")
                    self.output_text.append("This might be caused by issues in the audio file or limitations in the beat detection algorithm.")
                    self.handle_beat_detection_failure()
                else:
                    self.output_text.append(f"Error detecting beats: {str(e)}")
                    self.handle_beat_detection_failure()
            except Exception as e:
                self.output_text.append(f"Error detecting beats: {str(e)}")
                self.handle_beat_detection_failure()
            finally:
                self.progress_bar.setVisible(False)

    def handle_beat_detection_failure(self):
        self.output_text.append("Would you like to:")
        self.output_text.append("1. Set a default sample length")
        self.output_text.append("2. Try an alternative beat detection method")
        self.output_text.append("3. Continue without beat detection")
        
        choice, ok = QInputDialog.getItem(self, "Beat Detection Failed", 
                                          "Choose an option:", 
                                          ["Set default sample length", "Try alternative method", "Continue without beat detection"], 
                                          0, False)
        
        if ok:
            if choice == "Set default sample length":
                default_length, ok = QInputDialog.getDouble(self, "Set Default Sample Length", 
                                                            "Enter default sample length (in seconds):", 
                                                            1.0, 0.1, 10.0, 2)
                if ok:
                    self.detected_sample_length = default_length
                    self.sample_length_spin.setValue(self.detected_sample_length)
                    self.output_text.append(f"Default sample length set to {self.detected_sample_length:.2f} seconds")
            elif choice == "Try alternative method":
                self.output_text.append("Attempting alternative beat detection method...")
                # Implement an alternative beat detection method here
                # For now, we'll just set a default length
                self.detected_sample_length = 1.0
                self.sample_length_spin.setValue(self.detected_sample_length)
                self.output_text.append(f"Alternative method failed. Default sample length set to {self.detected_sample_length:.2f} seconds")
            else:
                self.output_text.append("Continuing without beat detection. You can manually set the sample length.")
        else:
            self.output_text.append("No option selected. You can manually set the sample length.")

    def execute_command(self, command):
        if self.sample_cutter:
            output = self.sample_cutter.handle_input(command)
            self.output_text.append(f"Command: {command}\nOutput: {output}")
        else:
            self.output_text.append("Please select an audio file first")

    def execute_custom_command(self):
        command = self.command_input.text()
        if command:
            self.execute_command(command)
            self.command_input.clear()

    def download_from_youtube(self):
        url, ok = QInputDialog.getText(self, "YouTube Downloader", "Enter YouTube URL:")
        if ok and url:
            self.output_text.append(f"Downloading from YouTube: {url}")
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
            self.output_text.append(f"Error downloading: {result}")
        elif isinstance(result, str) and os.path.exists(result):
            self.output_text.append(f"Download complete: {result}")
            self.audio_file_path = result
            self.file_label.setText(f"Selected file: {result}")
            self.output_text.append("File downloaded successfully. You can now select it to detect beats.")
            self.select_file()  # Automatically start beat detection
        else:
            self.output_text.append(f"Error: Invalid download result. Expected file path, got: {result}")

    def set_parameter(self):
        param = self.param_input.text().strip()
        if not param:
            self.output_text.append("Please enter a parameter")
            return

        if self.sample_cutter:
            output = self.sample_cutter.handle_input(param)
            self.output_text.append(f"Parameter set: {param}")
            self.output_text.append(f"Output: {output}")
            self.update_config_display()
        else:
            self.output_text.append("Please select an audio file first")

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
            self.output_text.append(config_text)
        else:
            self.output_text.append("No configuration available. Please select an audio file first.")

    def run_automixer(self):
        if not self.audio_file_path:
            self.log_message("Please select an audio file first")
            return

        if not self.sample_cutter or not hasattr(self.sample_cutter, 'beats'):
            self.log_message("Beats not detected. Please load the audio file and detect beats first.")
            return

        # Update AutoMixer configuration
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
