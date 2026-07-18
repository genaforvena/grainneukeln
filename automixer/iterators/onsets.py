"""Source onset detection, shared by the quantized (#5) and poly (#6) mixers.

Both macro-granular mixers cut grains at the source's transients rather than at arbitrary window
edges. This is the one onset pass they share: librosa onset detection on the pydub audio, optionally
snapped to a grid slot so the cut boundaries line up with where the grains are placed.
"""


def onset_positions(audio, snap_ms=0.0):
    """Onset positions of ``audio`` in ms (sorted, unique).

    ``snap_ms > 0`` snaps each onset to the nearest multiple of ``snap_ms`` (grid quantization of the
    cut boundaries). Returns ``[]`` when nothing latches — the caller falls back to a random position,
    never a beat floor (README's rhythm-seeking regime)."""
    import numpy as np
    import librosa

    samples = np.array(audio.get_array_of_samples()).astype(np.float32)
    if audio.channels == 2:
        samples = samples.reshape((-1, 2)).mean(axis=1)
    peak = np.max(np.abs(samples)) if samples.size else 0.0
    if peak > 0:
        samples = samples / peak
    sr = audio.frame_rate
    try:
        onset_times = librosa.onset.onset_detect(y=samples, sr=sr, units="time")
    except Exception:
        return []
    ms = [t * 1000 for t in onset_times]
    if snap_ms and snap_ms > 0:
        return sorted({int(round(round(m / snap_ms) * snap_ms)) for m in ms if m >= 0})
    return sorted({int(round(m)) for m in ms if m >= 0})
