import unittest

import numpy as np

from automixer.utils import beat_interval, calculate_step


class BeatIntervalTest(unittest.TestCase):
    def test_period_is_spacing_not_mean_of_positions(self):
        # Beats every 500ms. The PERIOD is 500 — not mean(positions)/4 (which calculate_step returns).
        beats = np.array([500, 1000, 1500, 2000, 2500, 3000])
        self.assertEqual(beat_interval(beats), 500)
        # The old base really is nowhere near the beat — this is why /2 /3 never subdivided the beat.
        self.assertNotEqual(calculate_step(beats), 500)

    def test_median_is_robust_to_a_dropped_beat(self):
        # One missing beat leaves a 1000ms gap; the median of {500,500,1000,500} is still 500.
        beats = np.array([500, 1000, 1500, 2500, 3000])
        self.assertEqual(beat_interval(beats), 500)

    def test_fewer_than_two_beats_is_unknowable(self):
        self.assertEqual(beat_interval(np.array([])), 0)
        self.assertEqual(beat_interval(np.array([500])), 0)


if __name__ == "__main__":
    unittest.main()
