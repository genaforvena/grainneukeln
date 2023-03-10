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


