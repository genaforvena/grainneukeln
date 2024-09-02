import sys
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                               QWidget, QPushButton, QFileDialog, QLabel, QTextEdit, 
                               QLineEdit)
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QToolTip
from cutter.sample_cut_tool import SampleCutter

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sample Cutter")
        self.setGeometry(100, 100, 600, 400)

        main_layout = QVBoxLayout()

        self.file_label = QLabel("No file selected")
        main_layout.addWidget(self.file_label)

        select_file_button = QPushButton("Select Audio File")
        select_file_button.clicked.connect(self.select_file)
        main_layout.addWidget(select_file_button)

        button_layout = QHBoxLayout()
        commands = ["p", "b", "l", "s", "cut", "automix"]
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

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        main_layout.addWidget(self.output_text)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        self.sample_cutter = None

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Audio File", "", "Audio Files (*.mp3 *.wav *.webm *.m4a)")
        if file_path:
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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set global tooltip style
    QToolTip.setFont(QFont('SansSerif', 10))
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
