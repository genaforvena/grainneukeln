from PySide6.QtWidgets import QMessageBox

class HelpDialog(QMessageBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("How to Use")
        self.setText("Granular Sampler and AutoMixer Instructions")
        self.setInformativeText(
            "1. Load Audio: Click 'Load Audio' to select a file or enter a YouTube URL.\n"
            "2. Configure AutoMixer: Adjust settings in the AutoMixer panel.\n"
            "3. Apply Configuration: Click 'Apply Configuration' to set your changes.\n"
            "4. Run AutoMixer: Click 'Run AutoMixer' to process your audio.\n"
            "5. Preview: Use 'Play Original' and 'Play Mixed' to hear results.\n"
            "6. Save: Click 'Save Mixed Audio' to export your processed audio.\n\n"
            "Hover over elements for more detailed information!"
        )
        self.setIcon(QMessageBox.Information)
