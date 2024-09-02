import os
from datetime import datetime
from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, 
                               QWidget, QPushButton, QFileDialog, QLabel, QTextEdit, 
                               QLineEdit, QComboBox, QDoubleSpinBox, QCheckBox, QToolTip,
                               QInputDialog, QProgressBar, QApplication)
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

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        button_layout = QHBoxLayout()
        commands = [
            ("p", "Play"),
            ("b", "Set Beginning"),
            ("l", "Set Length"),
            ("s", "Set Step"),
            ("cut", "Cut Sample"),
            ("f", "Forward"),
            ("r", "Rewind"),
            ("plot", "Plot Amplitude"),
            ("info", "Sample Info"),
            ("am", "AutoMix")
        ]
        for command, description in commands:
            button = QPushButton(command)
            button.clicked.connect(lambda checked, cmd=command: self.execute_command(cmd))
            button.setToolTip(description)
            button_layout.addWidget(button)

        main_layout.addLayout(button_layout)

        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("Enter custom command")
        main_layout.addWidget(self.command_input)

        execute_button = QPushButton("Execute Command")
        execute_button.clicked.connect(self.execute_custom_command)
        execute_button.setToolTip("Execute the custom command entered above")
        main_layout.addWidget(execute_button)

        # AutoMixer parameters
        automixer_layout = QVBoxLayout()
        automixer_layout.addWidget(QLabel("AutoMixer Parameters:"))

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["r", "3", "3w"])  # Add modes from README
        self.mode_combo.setToolTip("Select the AutoMixer mode")
        automixer_layout.addWidget(QLabel("Mode:"))
        automixer_layout.addWidget(self.mode_combo)

        self.sample_length_spin = QDoubleSpinBox()
        self.sample_length_spin.setRange(0.1, 10.0)
        self.sample_length_spin.setValue(1.0)
        self.sample_length_spin.setToolTip("Set the length of each sample in seconds")
        automixer_layout.addWidget(QLabel("Sample Length:"))
        automixer_layout.addWidget(self.sample_length_spin)

        self.sample_speed_spin = QDoubleSpinBox()
        self.sample_speed_spin.setRange(0.1, 2.0)
        self.sample_speed_spin.setValue(1.0)
        self.sample_speed_spin.setToolTip("Set the playback speed of samples")
        automixer_layout.addWidget(QLabel("Sample Speed:"))
        automixer_layout.addWidget(self.sample_speed_spin)

        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 2.0)
        self.speed_spin.setValue(1.0)
        self.speed_spin.setToolTip("Set the overall speed of the mixed audio")
        automixer_layout.addWidget(QLabel("Speed:"))
        automixer_layout.addWidget(self.speed_spin)

        self.verbose_checkbox = QCheckBox("Verbose Mode")
        self.verbose_checkbox.setToolTip("Enable detailed output during processing")
        automixer_layout.addWidget(self.verbose_checkbox)

        self.window_divider_spin = QDoubleSpinBox()
        self.window_divider_spin.setRange(1, 10)
        self.window_divider_spin.setValue(2)
        self.window_divider_spin.setToolTip("Set the window divider for sample selection")
        automixer_layout.addWidget(QLabel("Window Divider:"))
        automixer_layout.addWidget(self.window_divider_spin)

        main_layout.addLayout(automixer_layout)

        automix_button = QPushButton("Run AutoMixer")
        automix_button.clicked.connect(self.run_automixer)
        automix_button.setToolTip("Start the AutoMixer process")
        main_layout.addWidget(automix_button)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        main_layout.addWidget(self.output_text)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        self.sample_cutter = None
        self.audio_file_path = None
        self.detected_sample_length = None

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
                    self.sample_length_spin.setValue(self.detected_sample_length)
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

    def run_automixer(self):
        if not self.audio_file_path:
            self.output_text.append("Please select an audio file first")
            return

        if not self.sample_cutter or not hasattr(self.sample_cutter, 'beats'):
            self.output_text.append("Beats not detected. Please load the audio file and detect beats first.")
            return

        config = AutoMixerConfig(
            audio=self.audio_file_path,
            beats=self.sample_cutter.beats,
            sample_length=self.sample_length_spin.value(),
            sample_speed=self.sample_speed_spin.value(),
            mode=self.mode_combo.currentText(),
            speed=self.speed_spin.value(),
            is_verbose_mode_enabled=self.verbose_checkbox.isChecked(),
            window_divider=int(self.window_divider_spin.value())
        )

        runner = AutoMixerRunner()
        try:
            mix = runner.run(config)
            output_file = f"{os.path.splitext(os.path.basename(self.audio_file_path))[0]}___mix_cut{int(self.sample_length_spin.value()*1000)}-vtgsmlpr____" + \
                          f"{datetime.now().strftime('%Y_%m_%d_%H%M')}.mp3"
            mix.export(output_file, format="mp3")
            self.output_text.append(f"AutoMixer completed. Output saved as {output_file}")
        except Exception as e:
            self.output_text.append(f"Error running AutoMixer: {str(e)}")
