from PySide6.QtWidgets import QHBoxLayout, QLabel, QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit

class ModeSelector(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["rw"])  # Add more modes as needed
        self.mode_combo.setToolTip("Select the AutoMixer mode")
        self.addWidget(self.mode_combo)

    def get_value(self):
        return self.mode_combo.currentText()

class SpeedInput(QHBoxLayout):
    def __init__(self, label):
        super().__init__()
        self.addWidget(QLabel(f"{label}:"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 10.0)
        self.speed_spin.setSingleStep(0.1)
        self.speed_spin.setValue(1.0)
        self.speed_spin.setToolTip(f"Set the {label.lower()} of the mixed audio")
        self.addWidget(self.speed_spin)

    def get_value(self):
        return self.speed_spin.value()

class WindowDividerInput(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.addWidget(QLabel("Window Divider:"))
        self.window_spin = QSpinBox()
        self.window_spin.setRange(1, 10)
        self.window_spin.setValue(2)
        self.window_spin.setToolTip("Set the window divider for sample selection")
        self.addWidget(self.window_spin)

    def get_value(self):
        return self.window_spin.value()

class ChannelInput(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.addWidget(QLabel("Channels:"))
        self.channel_edit = QLineEdit("0,15000")
        self.channel_edit.setPlaceholderText("e.g., 0,15000")
        self.channel_edit.setToolTip("Set the frequency range for channels (low,high)")
        self.addWidget(self.channel_edit)

    def get_value(self):
        return self.channel_edit.text()

class SampleLengthInput(QHBoxLayout):
    def __init__(self):
        super().__init__()
        self.addWidget(QLabel("Sample Length:"))
        self.length_edit = QLineEdit()
        self.length_edit.setPlaceholderText("e.g., 1000 (in ms)")
        self.length_edit.setToolTip("Set the length of each sample in milliseconds")
        self.addWidget(self.length_edit)

    def get_value(self):
        return self.length_edit.text()

    def set_value(self, value):
        self.length_edit.setText(value)
