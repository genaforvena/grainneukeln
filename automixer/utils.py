def log_message(logger, message):
    if logger:
        logger.info(message)
    else:
        print(message)

import numpy as np

def calculate_step(beats):
    """Calculate the step size based on the beats."""
    if len(beats) == 0 or np.all(beats <= 0):
        return 1
    return max(1, int(np.mean(beats) / 4))
