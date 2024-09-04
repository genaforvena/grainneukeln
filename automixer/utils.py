def log_message(logger, message):
    if logger:
        logger.info(message)
    else:
        print(message)

def calculate_step(beats):
    """Calculate the step size based on the beats."""
    if beats <= 0:
        return 1
    return max(1, int(beats / 4))
