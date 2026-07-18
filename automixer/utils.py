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


def beat_interval(beats):
    """The real beat PERIOD in ms — the base value for grain length (``l = beat``).

    ``beats`` are cumulative beat POSITIONS (ms), so the period is the SPACING between
    consecutive beats, not their mean. (``calculate_step`` above takes ``mean(beats)/4``,
    which — since beats are positions — is a quarter of the mean *position*, i.e. roughly
    an eighth of the track length, and has nothing to do with the beat. That is why
    dividing it by 2/3 never produced a musical subdivision.) ``median(diff)`` is robust to
    detector jitter and the odd dropped/double beat. Returns 0 when the beat is unknowable
    (< 2 beats), so the caller can fall back.
    """
    beats = np.asarray(beats)
    if len(beats) < 2:
        return 0
    diffs = np.diff(beats)
    diffs = diffs[diffs > 0]
    if len(diffs) == 0:
        return 0
    return max(1, int(round(float(np.median(diffs)))))
