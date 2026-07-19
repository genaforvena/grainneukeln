import unittest
from automixer.config import parse_stream_spec


class ParseStreamSpecTest(unittest.TestCase):
    def test_empty_is_none(self):
        self.assertIsNone(parse_stream_spec(""))
        self.assertIsNone(parse_stream_spec("   "))
        self.assertIsNone(parse_stream_spec(None))

    def test_bare_ratios_full_band(self):
        streams = parse_stream_spec("3;2")
        self.assertEqual([s["ratio"] for s in streams], [3, 2])
        for s in streams:
            self.assertNotIn("channels", s)
            self.assertNotIn("length", s)

    def test_banded_and_length(self):
        streams = parse_stream_spec("4@1.5:1-2000;3:6000-15000")
        self.assertEqual(streams[0]["ratio"], 4)
        self.assertEqual(streams[0]["length"], 1.5)
        self.assertEqual(streams[0]["channels"][0].low_pass, 1)
        self.assertEqual(streams[0]["channels"][0].high_pass, 2000)
        self.assertEqual(streams[1]["ratio"], 3)
        self.assertEqual(streams[1]["channels"][0].low_pass, 6000)

    def test_trailing_semicolon_ignored(self):
        self.assertEqual(len(parse_stream_spec("3;2;")), 2)

    def test_garbage_raises(self):
        # a non-integer ratio is a real error the caller must surface, not a silent None
        with self.assertRaises(ValueError):
            parse_stream_spec("notaratio")


if __name__ == "__main__":
    unittest.main()
