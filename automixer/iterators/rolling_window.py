from itertools import tee

def rolling_window(iterable, window_divider):
    # A window is at least ONE beat. Without the clamp, a divider larger than the beat count floors
    # to 0 -> tee(iterable, 0) is empty -> zip() over no iterators yields nothing, so the mix comes
    # out empty, main.py still writes a 261-byte mp3 and still exits 0. A short source is exactly
    # where this bites: a 5-beat record takes w=4 and w=5 fine and grinds to silence on w=6 and w=8
    # (half the divider pool the sound reflex rotates over). The divider asks for granularity; when
    # it asks for finer than one beat per window, one beat per window IS the answer.
    beats_window_size = max(1, len(iterable) // window_divider)
    # Create n independent iterators from the original iterable
    iterators = tee(iterable, beats_window_size)

    # Advance each iterator by i elements where i is its index
    for i, it in enumerate(iterators):
        for j in range(i):
            next(it, None)

    # Use zip to group elements from each iterator into tuples
    return zip(*iterators)


