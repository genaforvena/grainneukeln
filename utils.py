from PySide6.QtWidgets import QMessageBox

def show_error_message(parent, title, message):
    QMessageBox.critical(parent, title, message)

def show_info_message(parent, title, message):
    QMessageBox.information(parent, title, message)

def log_message(logger, message):
    if logger:
        logger.log_message(message)
    print(message)  # Also print to console for debugging
