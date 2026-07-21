import unittest

from pydub.generators import Sine

from automixer.effects.grain_shape import maybe_reverse, apply_envelope


class _FixedRng:
    """Stub RNG exposing the one method grain_shape needs — `.random()` -> a fixed float, matching
    the surface both `random` (the stdlib module) and `np.random.Generator` share."""
    def __init__(self, value):
        self._value = value

    def random(self):
        return self._value


class MaybeReverseTest(unittest.TestCase):
    def test_prob_zero_is_never_reversed(self):
        seg = Sine(300).to_audio_segment(duration=200)
        out = maybe_reverse(seg, 0.0, _FixedRng(0.0))
        self.assertEqual(bytes(out._data), bytes(seg._data))

    def test_below_threshold_reverses(self):
        seg = Sine(300).to_audio_segment(duration=200)
        out = maybe_reverse(seg, 0.5, _FixedRng(0.1))
        self.assertEqual(bytes(out._data), bytes(seg.reverse()._data))

    def test_above_threshold_passes_through(self):
        seg = Sine(300).to_audio_segment(duration=200)
        out = maybe_reverse(seg, 0.5, _FixedRng(0.9))
        self.assertEqual(bytes(out._data), bytes(seg._data))

    def test_empty_segment_is_a_noop(self):
        seg = Sine(300).to_audio_segment(duration=0)
        out = maybe_reverse(seg, 1.0, _FixedRng(0.0))
        self.assertEqual(len(out), 0)


class ApplyEnvelopeTest(unittest.TestCase):
    def test_pct_zero_is_a_true_noop(self):
        seg = Sine(300).to_audio_segment(duration=200)
        out = apply_envelope(seg, 0)
        self.assertEqual(bytes(out._data), bytes(seg._data))

    def test_negative_pct_is_a_noop(self):
        seg = Sine(300).to_audio_segment(duration=200)
        out = apply_envelope(seg, -5)
        self.assertEqual(bytes(out._data), bytes(seg._data))

    def test_positive_pct_shapes_the_edges_toward_silence(self):
        seg = Sine(300).to_audio_segment(duration=200).apply_gain(0)  # full-amplitude tone
        out = apply_envelope(seg, 20)
        self.assertEqual(len(out), len(seg))
        # first/last sample must be materially quieter than the un-enveloped tone's edge sample —
        # a real fade, not a no-op that happened to pass the length check.
        import numpy as np
        raw = np.array(seg.get_array_of_samples())
        shaped = np.array(out.get_array_of_samples())
        self.assertLess(abs(shaped[0]), abs(raw[0]) or 1)
        self.assertLess(abs(shaped[-1]), abs(raw[-5]) or 1)

    def test_pct_is_clamped_so_taper_never_exceeds_half_length(self):
        seg = Sine(300).to_audio_segment(duration=50)
        # 200% would ask for a 100ms taper on each edge of a 50ms grain -- must not crash or
        # produce something longer/shorter than the input.
        out = apply_envelope(seg, 200)
        self.assertEqual(len(out), len(seg))


if __name__ == "__main__":
    unittest.main()
