import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QFileDialog, QLabel
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QToolTip
from cutter.sample_cut_tool import SampleCutter

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sample Cutter")
        self.setGeometry(100, 100, 300, 200)

        layout = QVBoxLayout()

        self.file_label = QLabel("No file selected")
        layout.addWidget(self.file_label)

        select_file_button = QPushButton("Select Audio File")
        select_file_button.clicked.connect(self.select_file)
        layout.addWidget(select_file_button)

        cut_sample_button = QPushButton("Cut Sample")
        cut_sample_button.clicked.connect(self.cut_sample)
        layout.addWidget(cut_sample_button)

        central_widget = QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

        self.sample_cutter = None

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Audio File", "", "Audio Files (*.mp3 *.wav *.webm *.m4a)")
        if file_path:
            self.file_label.setText(f"Selected file: {file_path}")
            self.sample_cutter = SampleCutter(file_path, "samples")

    def cut_sample(self):
        if self.sample_cutter:
            self.sample_cutter.cut_track("cut")
        else:
            print("Please select an audio file first")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set global tooltip style
    QToolTip.setFont(QFont('SansSerif', 10))
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
