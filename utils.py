from PySide6.QtWidgets import QMessageBox

def show_error_message(parent, title, message):
    QMessageBox.critical(parent, title, message)

def show_info_message(parent, title, message):
    QMessageBox.information(parent, title, message)

def log_message(logger, message):
    if logger:
        logger.log_message(message)
    print(message)  # Also print to console for debugging

def calculate_step(beats):
    """
    Calculate the step size as the average distance between the beats.
    
    :param beats: List of beat positions
    :return: Average step size
    """
    try:
        if len(beats) < 2:
            raise ValueError("At least two beats are required to calculate step size")
        
        step = sum(beats[i] - beats[i-1] for i in range(1, len(beats))) / (len(beats) - 1)
        return step
    except Exception as e:
        log_message(None, f"Error calculating step size: {str(e)}")
        return 0  # Return a default value or raise the exception based on your error handling strategy
