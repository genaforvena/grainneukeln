from itertools import tee


def rolling_window(iterable, window_divider):
    beats_window_size = len(iterable) // window_divider
    # Create n independent iterators from the original iterable
    iterators = tee(iterable, beats_window_size)

    # Advance each iterator by i elements where i is its index
    for i, it in enumerate(iterators):
        for j in range(i):
            next(it, None)

    # Use zip to group elements from each iterator into tuples
    return zip(*iterators)


class RollingWindowIterator:
    def __init__(self, audio, beats, window_divider, step_size):
        self.audio = audio
        self.beats = beats
        self.window_divider = window_divider
        # Cut the beats array into equal sized windows of size window_divider
        self.beats_window_size = len(beats) // window_divider
        self.beats_windows = list(make_windows(beats, self.beats_window_size))
        # self.beats_windows = [x for x in self.beats_windows for _ in range(window_divider)]
        self.audio_window_size = len(audio[self.beats_windows[0][0]:self.beats_windows[0][1]])
        self.step_size = step_size

    def __iter__(self):
        beat_window_index = 0
        for audio_index in self.audio:
            print("audio_index: ", audio_index)
            if audio_index >= self.beats[beat_window_index]:
                print("beats_index: ", beat_window_index)
                beat_window_index += 1
            yield self.beats_windows[beat_window_index]


