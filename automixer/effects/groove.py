"""Swing / groove-template micro-timing (issue #8).

Dead-on-grid placement marches mechanically. These offsets make the output breathe: a swing % delays
every off-beat subdivision (classic 2:1 shuffle), or an arbitrary groove template applies per-slot ms
offsets. Applied in a mixer's placement step, keyed by each grain's subdivision index.

Swing convention (so ``swing=0`` is a genuine no-op AND ``swing=66`` is the classic 2:1 shuffle):
``delay_fraction = max(0, (swing - 50) / 50)``. So swing <= 50 (including 0) delays nothing —
bit-identical to straight placement — while swing = 66 delays the off-beat by ``0.32 * sub_ms``,
putting it at ~2/3 of the beat (on:off ~= 2:1).
"""


def swing_offset(slot_index, swing_pct, sub_ms):
    """Millisecond delay for the grain on subdivision ``slot_index`` under ``swing_pct`` swing.

    On-beats (even slots) never move; off-beats (odd slots) are delayed. ``swing_pct <= 50`` (incl. 0)
    is a no-op — zero delay, so straight placement is bit-identical to swing-off."""
    if slot_index % 2 == 0:
        return 0.0
    delay_fraction = max(0.0, (float(swing_pct) - 50.0) / 50.0)
    return delay_fraction * float(sub_ms)


def groove_offsets(n_slots, swing_pct=0, sub_ms=0.0, template=None):
    """Per-slot ms offsets for ``n_slots`` placement slots.

    A ``template`` (list of ms offsets) wins if given and is applied cyclically; otherwise the swing
    rule applies. With no template and ``swing_pct <= 50`` every offset is 0 (genuine no-op)."""
    if template:
        return [float(template[i % len(template)]) for i in range(n_slots)]
    return [swing_offset(i, swing_pct, sub_ms) for i in range(n_slots)]
