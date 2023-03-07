import unittest
from cutter.automixer.mixers.iterators.window import WindowIterator


class TestWindowIterator(unittest.TestCase):
    def setUp(self):
        self.audio = list(range(0, 3200))
        self.beats = list(range(0, 3200, 2))
        self.window_divider = 2
        self.step_size = 1
        self.iterator = WindowIterator(self.audio, self.beats, self.window_divider, self.step_size)

    def test_iterator_returns_correct_number_of_windows(self):
        expected_num_windows = 3200
        actual_num_windows = len(list(self.iterator))
        self.assertEqual(actual_num_windows, expected_num_windows)

    def test_iterator_returns_correct_number_of_windows_when_step_size_3(self):
        self.step_size = 4
        self.iterator = WindowIterator(self.audio, self.beats, self.window_divider, self.step_size)
        actual_num_windows = len(list(self.iterator))
        self.assertEqual(actual_num_windows, 800)

    def test_iterator_correct_values_when_window_1(self):
        self.window_divider = 1
        self.iterator = WindowIterator(self.audio, self.beats, self.window_divider, self.step_size)
        actual_values = [window for window in self.iterator]
        self.assertEqual(actual_values[0], [0, self.beats[-1]])
        self.assertEqual(actual_values[5], [0, self.beats[-1]])
        self.assertEqual(actual_values[-1], [0, self.beats[-1]])

    def test_iterator_correct_values_when_step_2(self):
        self.window_divider = 1
        self.step_size = 2
        self.iterator = WindowIterator(self.audio, self.beats, self.window_divider, self.step_size)
        actual_values = [window for window in self.iterator]
        self.assertEqual(actual_values[0], [self.beats[0], self.beats[len(self.beats) - 1]])
        self.assertEqual(actual_values[-1], [self.beats[0], self.beats[len(self.beats) - 1]])

    def test_iterator_returns_correct_values_when_iterator_2(self):
        self.window_divider = 2
        self.iterator = WindowIterator(self.audio, self.beats, self.window_divider, self.step_size)
        actual_values = [window for window in self.iterator]
        print("Actual: ", actual_values)
        # self.assertEqual(expected_values, actual_values)
