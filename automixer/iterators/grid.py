"""Euclidean rhythm + beat-subdivision slot grid — the skeleton of the quantized mixer (issue #5).

Where `rolling_window` hands the rw mixer a *window of beats* to pick from at random, this module
hands the quantized mixer an explicit **placement grid**: subdivide the beat period into n slots and
fire a grain only on the slots a euclidean pattern E(k, n) marks as hits. The result has a *designed*
groove (a tresillo, a cinquillo, four-on-the-floor) rather than the rw mixer's uniform random fill —
and the placement is fully deterministic given (beat_period, pattern, span), which is the property
issue #5's acceptance asserts (two runs differ in grain CONTENT but not in grid PLACEMENT).
"""


def euclidean(k, n):
    """The canonical **Bjorklund** euclidean rhythm: k hits spread as evenly as the integers allow
    over n slots, returned as a 0/1 list.

    Bjorklund (not the cheaper ``(i*k)%n < k`` bresenham) because the acceptance names *specific*
    patterns by their canonical rotation: E(3,8) must be the tresillo ``[1,0,0,1,0,0,1,0]`` (hits on
    0,3,6), E(5,8) the cinquillo ``[1,0,1,1,0,1,1,0]``. The bresenham form yields the same gap
    multiset but a *rotated* pattern (E(3,8) -> hits on 2,5,7), which fails "produces the tresillo".

    Degenerate cases are clamped, never raised: k<=0 -> all rests, k>=n -> all hits, n<=0 -> empty.
    """
    if n <= 0:
        return []
    k = max(0, min(int(k), int(n)))
    if k == 0:
        return [0] * n
    if k == n:
        return [1] * n

    groups = [[1] for _ in range(k)]
    remainders = [[0] for _ in range(n - k)]
    while len(remainders) > 1:
        count = min(len(groups), len(remainders))
        if len(groups) > len(remainders):
            leftover = groups[count:]
        else:
            leftover = remainders[count:]
        paired = [groups[i] + remainders[i] for i in range(count)]
        groups = paired
        remainders = leftover

    pattern = []
    for g in groups:
        pattern += g
    for r in remainders:
        pattern += r
    return pattern


def grid_slots(beat_period, pattern, total_ms):
    """Tile ``pattern`` across ``total_ms`` and return the OUTPUT position (ms, float) of every HIT.

    The n slots of ``pattern`` span exactly one beat, so ``slot = beat_period / n`` — subdividing the
    beat the same way the README's ``l /2 /3`` metric family does, keeping every grain start on an
    integer subdivision of the imagined pulse. Slots are laid end to end from 0; the pattern repeats
    (bar after bar) until ``total_ms`` is covered, and only slots the pattern marks ``1`` are emitted.
    """
    if not pattern or beat_period <= 0 or total_ms <= 0:
        return []
    n = len(pattern)
    slot_ms = float(beat_period) / n
    if slot_ms <= 0:
        return []
    num_slots = int(total_ms // slot_ms)
    return [i * slot_ms for i in range(num_slots) if pattern[i % n]]
