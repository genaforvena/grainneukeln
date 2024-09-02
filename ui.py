import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QToolTip
from main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set global tooltip style
    QToolTip.setFont(QFont('SansSerif', 10))
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
