from PySide6.QtWidgets import QGroupBox, QVBoxLayout
from config_inputs import ModeSelector, SpeedInput, WindowDividerInput, ChannelInput, SampleLengthInput
from progress_display import ProgressDisplay
from config_buttons import ConfigButtons
from workers import AutoMixerWorker
from utils import show_error_message, show_info_message, log_message

class AutoMixerConfigPanel(QGroupBox):
    def __init__(self, sample_cutter):
        super().__init__("AutoMixer Configuration")
        self.sample_cutter = sample_cutter
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        self.mode_selector = ModeSelector()
        layout.addLayout(self.mode_selector)

        self.speed_input = SpeedInput("Speed")
        layout.addLayout(self.speed_input)

        self.sample_speed_input = SpeedInput("Sample Speed")
        layout.addLayout(self.sample_speed_input)

        self.window_divider_input = WindowDividerInput()
        layout.addLayout(self.window_divider_input)

        self.channel_input = ChannelInput()
        layout.addLayout(self.channel_input)

        self.sample_length_input = SampleLengthInput()
        layout.addLayout(self.sample_length_input)

        self.config_buttons = ConfigButtons(self.apply_config, self.run_automixer)
        layout.addWidget(self.config_buttons)

        self.progress_display = ProgressDisplay()
        layout.addWidget(self.progress_display)

        self.setLayout(layout)

    def set_detected_sample_length(self, length):
        self.sample_length_input.set_value(str(int(length)))

    def apply_config(self):
        config_command = f"amc m {self.mode_selector.get_value()} "
        config_command += f"s {self.speed_input.get_value()} "
        config_command += f"ss {self.sample_speed_input.get_value()} "
        config_command += f"w {self.window_divider_input.get_value()} "
        config_command += f"c {self.channel_input.get_value()} "
        if self.sample_length_input.get_value():
            config_command += f"l {self.sample_length_input.get_value()}"
        
        self.sample_cutter.config_automix(config_command)
        log_message(self, f"AutoMixer configuration applied: {config_command}")

    def run_automixer(self):
        self.worker = AutoMixerWorker(self.sample_cutter)
        self.worker.finished.connect(self.on_automixer_finished)
        self.worker.progress.connect(self.progress_display.set_progress)
        self.worker.start()
        self.config_buttons.set_run_enabled(False)
        log_message(self, "AutoMixer process started...")

    def on_automixer_finished(self, success, message):
        self.config_buttons.set_run_enabled(True)
        if success:
            log_message(self, message)
            show_info_message(self, "AutoMixer Complete", message)
        else:
            log_message(self, f"Error: {message}")
            show_error_message(self, "Error", f"An error occurred while running AutoMixer: {message}")

    def log_message(self, message):
        self.progress_display.log_message(message)
