import sys
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                               QWidget, QPushButton, QFileDialog, QLabel, QTextEdit, 
                               QLineEdit, QComboBox, QDoubleSpinBox, QCheckBox)
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QToolTip
from cutter.sample_cut_tool import SampleCutter
from automixer.config import AutoMixerConfig
from automixer.runner import AutoMixerRunner

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sample Cutter and AutoMixer")
        self.setGeometry(100, 100, 800, 600)

        main_layout = QVBoxLayout()

        self.file_label = QLabel("No file selected")
        main_layout.addWidget(self.file_label)

        select_file_button = QPushButton("Select Audio File")
        select_file_button.clicked.connect(self.select_file)
        main_layout.addWidget(select_file_button)

        button_layout = QHBoxLayout()
        commands = ["p", "b", "l", "s", "cut"]
        for command in commands:
            button = QPushButton(command)
            button.clicked.connect(lambda checked, cmd=command: self.execute_command(cmd))
            button_layout.addWidget(button)

        main_layout.addLayout(button_layout)

        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("Enter custom command")
        main_layout.addWidget(self.command_input)

        execute_button = QPushButton("Execute Command")
        execute_button.clicked.connect(self.execute_custom_command)
        main_layout.addWidget(execute_button)

        # AutoMixer parameters
        automixer_layout = QVBoxLayout()
        automixer_layout.addWidget(QLabel("AutoMixer Parameters:"))

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["rw"])  # Add more modes if available
        automixer_layout.addWidget(QLabel("Mode:"))
        automixer_layout.addWidget(self.mode_combo)

        self.sample_length_spin = QDoubleSpinBox()
        self.sample_length_spin.setRange(0.1, 10.0)
        self.sample_length_spin.setValue(1.0)
        automixer_layout.addWidget(QLabel("Sample Length:"))
        automixer_layout.addWidget(self.sample_length_spin)

        self.sample_speed_spin = QDoubleSpinBox()
        self.sample_speed_spin.setRange(0.1, 2.0)
        self.sample_speed_spin.setValue(1.0)
        automixer_layout.addWidget(QLabel("Sample Speed:"))
        automixer_layout.addWidget(self.sample_speed_spin)

        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 2.0)
        self.speed_spin.setValue(1.0)
        automixer_layout.addWidget(QLabel("Speed:"))
        automixer_layout.addWidget(self.speed_spin)

        self.verbose_checkbox = QCheckBox("Verbose Mode")
        automixer_layout.addWidget(self.verbose_checkbox)

        self.window_divider_spin = QDoubleSpinBox()
        self.window_divider_spin.setRange(1, 10)
        self.window_divider_spin.setValue(2)
        automixer_layout.addWidget(QLabel("Window Divider:"))
        automixer_layout.addWidget(self.window_divider_spin)

        main_layout.addLayout(automixer_layout)

        automix_button = QPushButton("Run AutoMixer")
        automix_button.clicked.connect(self.run_automixer)
        main_layout.addWidget(automix_button)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        main_layout.addWidget(self.output_text)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        self.sample_cutter = None
        self.audio_file_path = None

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Audio File", "", "Audio Files (*.mp3 *.wav *.webm *.m4a)")
        if file_path:
            self.audio_file_path = file_path
            self.file_label.setText(f"Selected file: {file_path}")
            self.sample_cutter = SampleCutter(file_path, "samples")
            self.output_text.append(f"Loaded file: {file_path}")

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

    def run_automixer(self):
        if not self.audio_file_path:
            self.output_text.append("Please select an audio file first")
            return

        config = AutoMixerConfig(
            audio=self.audio_file_path,
            beats=self.sample_cutter._beats if self.sample_cutter else None,
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
            output_file = "output_mix.mp3"
            mix.export(output_file, format="mp3")
            self.output_text.append(f"AutoMixer completed. Output saved as {output_file}")
        except Exception as e:
            self.output_text.append(f"Error running AutoMixer: {str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set global tooltip style
    QToolTip.setFont(QFont('SansSerif', 10))
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
