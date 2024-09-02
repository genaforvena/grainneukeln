from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton

class ConfigButtons(QWidget):
    def __init__(self, apply_callback, run_callback):
        super().__init__()
        layout = QHBoxLayout(self)
        
        self.apply_button = QPushButton("Apply Configuration")
        self.apply_button.clicked.connect(apply_callback)
        self.apply_button.setToolTip("Apply the current configuration settings")
        layout.addWidget(self.apply_button)

        self.run_button = QPushButton("Run AutoMixer")
        self.run_button.clicked.connect(run_callback)
        self.run_button.setToolTip("Start the AutoMixer process with current settings")
        layout.addWidget(self.run_button)

    def set_run_enabled(self, enabled):
        self.run_button.setEnabled(enabled)
