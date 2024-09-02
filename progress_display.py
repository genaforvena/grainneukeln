from PySide6.QtWidgets import QVBoxLayout, QProgressBar, QPlainTextEdit

class ProgressDisplay(QVBoxLayout):
    def __init__(self):
        super().__init__()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setToolTip("Shows the progress of the AutoMixer process")
        self.addWidget(self.progress_bar)

        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setToolTip("Displays logs and messages from the application")
        self.addWidget(self.log_display)

    def set_progress(self, value):
        self.progress_bar.setValue(value)

    def log_message(self, message):
        self.log_display.appendPlainText(message)
