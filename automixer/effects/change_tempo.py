import numpy as np
import pydub

# Time-stretch (tempo change without pitch shift). Originally pyrubberband, which needs the external
# `rubberband` CLI binary (not installable without root here). Swapped to librosa.effects.time_stretch
# — pure Python, no system binary, same semantics (rate > 1 -> faster/shorter). Creative behaviour
# unchanged; just the engine. — mesh revive 2026-06-21


def change_audioseg_tempo(audiosegment, speed, verbose=True):
    import librosa

    if verbose:
        print("Changing playback speed to " + str(speed))
        print("Audio length: " + str(len(audiosegment)))

    sample_rate = audiosegment.frame_rate
    channels = audiosegment.channels
    # pydub samples are interleaved ints; normalise to float [-1, 1] for librosa.
    y = np.array(audiosegment.get_array_of_samples()).astype(np.float32) / (2 ** 15)

    if channels == 2:
        y = y.reshape((-1, 2)).T  # (2, n), librosa stretches per-channel
        stretched = [
            librosa.effects.time_stretch(np.ascontiguousarray(y[c]), rate=speed)
            for c in range(2)
        ]
        n = min(len(stretched[0]), len(stretched[1]))
        out = np.stack([stretched[0][:n], stretched[1][:n]], axis=1).flatten()
    else:
        out = librosa.effects.time_stretch(np.ascontiguousarray(y), rate=speed)

    # Scale by 2**15 - 1, not 2**15: a clipped +1.0 sample * 32768 = 32768 overflows int16 and wraps
    # to -32768 (a sign flip -> a click -> broadband energy that corrupts pitch on near-full-scale
    # grains). The phase vocoder routinely overshoots past +-1 on a loud tone, so this bit. Round
    # rather than truncate toward zero.
    y_int = np.round(np.clip(out, -1.0, 1.0) * (2 ** 15 - 1)).astype(np.int16)
    new_seg = pydub.AudioSegment(
        y_int.tobytes(), frame_rate=sample_rate, sample_width=2, channels=channels
    )

    if verbose:
        print("New audio length: " + str(len(new_seg)))
    return new_seg


def snap_to_length(audiosegment, target_ms, verbose=False):
    """Pitch-preserving time-stretch of a grain to land EXACTLY at ``target_ms``.

    A grain cut off-grid or from material that doesn't fill its beat slot lands short/long and smears
    the groove. This stretches it (same phase-vocoder engine as ``change_audioseg_tempo``, so pitch is
    unchanged) to the target beat/subdivision length, then trims/pads by a few ms for a sample-exact
    fit (librosa's stretch is approximate). Returns the input untouched when it is already on length
    or the target is degenerate."""
    import pydub as _pydub

    cur = len(audiosegment)
    target_ms = int(round(target_ms))
    if cur <= 0 or target_ms <= 0 or cur == target_ms:
        return audiosegment

    # librosa time_stretch: out_len = in_len / rate. To reach target_ms from cur, rate = cur/target.
    rate = cur / float(target_ms)
    stretched = change_audioseg_tempo(audiosegment, rate, verbose=verbose)

    if len(stretched) > target_ms:
        return stretched[:target_ms]
    if len(stretched) < target_ms:
        pad = _pydub.AudioSegment.silent(
            duration=target_ms - len(stretched), frame_rate=stretched.frame_rate
        ).set_channels(stretched.channels)
        return stretched + pad
    return stretched
