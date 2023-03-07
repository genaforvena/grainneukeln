class WindowIterator:
    def __init__(self, audio, beats, window_divider, step_size):
        self.audio = audio
        self.beats = beats
        self.window_divider = window_divider
        # Cut the beats array into equal sized windows of size window_divider
        self.beats_window_size = len(beats) // window_divider
        self.beats_windows = list(make_windows(beats, self.beats_window_size))
        self.beats_windows = [x for x in self.beats_windows for _ in range(self.beats_window_size)]
        self.audio_window_size = len(audio[self.beats_windows[0][0]:self.beats_windows[0][1]])
        self.step_size = step_size

    def __iter__(self):
        for beat_window in self.beats_windows:
            yield beat_window

def make_windows(beats, window_size):
    for i, beat in enumerate(beats):
        if (i + window_size) > len(beats) - 1:
            if i == 0:
                frozenI = i
            elif 'frozenI' in locals() and frozenI is not None:
                frozenI = frozenI
            else:
                frozenI = i
            yield [beats[frozenI:][0], beats[frozenI:][-1]]
        else:
            yield [beats[i:i + window_size][0], beats[i:i + window_size][-1]]

