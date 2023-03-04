import numpy as np
import pydub
import pyrubberband as pyrb


class ChangeTempo:

    def change_audioseg_tempo(self, audiosegment, speed):
        print("Changing playback speed to " + str(speed))
        print("Audio length: " + str(len(audiosegment)))
        y = np.array(audiosegment.get_array_of_samples())
        if audiosegment.channels == 2:
            y = y.reshape((-1, 2))

        sample_rate = audiosegment.frame_rate

        y_fast = pyrb.time_stretch(y, sample_rate, speed)

        channels = 2 if (y_fast.ndim == 2 and y_fast.shape[1] == 2) else 1
        y = np.int16(y_fast * 2 ** 15)

        new_seg = pydub.AudioSegment(y.tobytes(), frame_rate=sample_rate, sample_width=2, channels=channels)

        print("New audio length: " + str(len(new_seg)))
        return new_seg