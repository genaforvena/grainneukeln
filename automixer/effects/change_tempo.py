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

    y_int = np.int16(np.clip(out, -1.0, 1.0) * (2 ** 15))
    new_seg = pydub.AudioSegment(
        y_int.tobytes(), frame_rate=sample_rate, sample_width=2, channels=channels
    )

    if verbose:
        print("New audio length: " + str(len(new_seg)))
    return new_seg
