"""The amc grammar bridge — parse in, print out, round-trip.

These are the gates on the TUI's CLI parity claim: if a token the CLI accepts does not land on the
state here, the claim is false. Each test asserts a CONCRETE field value, never just "no error"
(a parser that silently drops every token also raises no error).
"""
import unittest

from tui.amc import (apply_amc, format_amc, format_bands, is_series, parse_amc, parse_bands)
from tui.state import SessionState, TrackSpec


class ParseAmcTest(unittest.TestCase):
    def test_every_value_key_lands_on_the_state(self):
        s = SessionState(sample_length_ms=500)
        errs = apply_amc(s, "amc m q l 250 w 4 s 0.8 ss 1.25 ek 5 en 16 lk 9 lib con "
                            "sw 66 fg -9 env 12 rv 0.4 seed 42 src2 /tmp/b.mp3")
        self.assertEqual(errs, [])
        self.assertEqual(s.mode, "q")
        self.assertEqual(s.sample_length_ms, 250)
        self.assertEqual(s.window_divider, 4)
        self.assertEqual(s.speed, 0.8)
        self.assertEqual(s.sample_speed, 1.25)
        self.assertEqual(s.euclid_k, 5)
        self.assertEqual(s.euclid_n, 16)
        self.assertEqual(s.lib_clusters, 9)
        self.assertEqual(s.lib_policy, "contrast")
        self.assertEqual(s.swing, 66.0)
        self.assertEqual(s.fill_gain_db, -9.0)
        self.assertEqual(s.env_pct, 12.0)
        self.assertEqual(s.reverse_prob, 0.4)
        self.assertEqual(s.seed, 42)
        self.assertEqual(s.source2_path, "/tmp/b.mp3")

    def test_flags(self):
        s = SessionState()
        apply_amc(s, "snap nofill")
        self.assertTrue(s.snap)
        self.assertFalse(s.fill)
        apply_amc(s, "nosnap fill")
        self.assertFalse(s.snap)
        self.assertTrue(s.fill)

    def test_length_ratio_resolves_against_current(self):
        s = SessionState(sample_length_ms=480)
        apply_amc(s, "l /3")
        self.assertEqual(s.sample_length_ms, 160)
        apply_amc(s, "l *2")
        self.assertEqual(s.sample_length_ms, 320)

    def test_leading_amc_token_optional(self):
        a, b = SessionState(), SessionState()
        apply_amc(a, "amc w 5")
        apply_amc(b, "w 5")
        self.assertEqual(a.window_divider, b.window_divider, 5)

    def test_scan_is_pairwise_not_index_lookup(self):
        """A repeated key must apply its LAST value; the CLI's args.index() applies the first.

        Mutation gate: with an index-based parser this returns w=2, not w=7."""
        s = SessionState()
        apply_amc(s, "w 2 s 1.0 w 7")
        self.assertEqual(s.window_divider, 7)

    def test_lib_as_a_mode_value_is_not_read_as_a_policy(self):
        """`m lib` must set the MODE and leave the policy alone — the ambiguity that crashed
        config_automix before its own special case landed."""
        s = SessionState(lib_policy="contrast")
        errs = apply_amc(s, "m lib")
        self.assertEqual(errs, [])
        self.assertEqual(s.mode, "lib")
        self.assertEqual(s.lib_policy, "contrast")

    def test_errors_are_collected_and_the_good_half_still_applies(self):
        s = SessionState()
        errs = apply_amc(s, "w 4 m nonsense zzz 1")
        self.assertEqual(s.window_divider, 4)      # the good token landed
        self.assertEqual(s.mode, "rw")             # the bad one did not
        self.assertEqual(len(errs), 2, errs)
        self.assertTrue(any("nonsense" in e for e in errs))
        self.assertTrue(any("zzz" in e for e in errs))

    def test_out_of_range_is_an_error_not_a_clamp(self):
        s = SessionState()
        errs = apply_amc(s, "s 99")
        self.assertEqual(s.speed, 1.0)
        self.assertTrue(errs and "out of range" in errs[0])

    def test_euclid_k_greater_than_n_rejected_as_a_pair(self):
        s = SessionState()
        errs = apply_amc(s, "ek 9 en 4")
        self.assertTrue(any("must be <= n" in e for e in errs))
        self.assertEqual((s.euclid_k, s.euclid_n), (3, 8))   # neither half applied

    def test_missing_value_reported(self):
        s = SessionState()
        errs = apply_amc(s, "w")
        self.assertTrue(errs and "missing value" in errs[0])

    def test_bad_poly_spec_reported_not_stored(self):
        s = SessionState()
        errs = apply_amc(s, "pr not-a-spec")
        self.assertTrue(errs)
        self.assertEqual(s.streams_spec, "")


class BandsTest(unittest.TestCase):
    def test_bands_parse_with_source_b_prefix(self):
        tracks = parse_bands("0,250;2:900,7000")
        self.assertEqual(len(tracks), 2)
        self.assertEqual((tracks[0].low, tracks[0].high, tracks[0].source2), (0, 250, False))
        self.assertEqual((tracks[1].low, tracks[1].high, tracks[1].source2), (900, 7000, True))
        self.assertTrue(all(not t.bypass for t in tracks), "a NAMED band is a real filter")

    def test_raw_is_the_absent_c_default(self):
        tracks = parse_bands("raw")
        self.assertEqual(len(tracks), 1)
        self.assertTrue(tracks[0].bypass)

    def test_round_trip(self):
        for spec in ("raw", "0,250", "0,250;2:900,7000"):
            self.assertEqual(format_bands(parse_bands(spec)), spec)

    def test_invalid_band_raises(self):
        with self.assertRaises(Exception):
            parse_bands("250,0")
        with self.assertRaises(Exception):
            parse_bands("nope")

    def test_c_token_replaces_the_track_list(self):
        s = SessionState()
        apply_amc(s, "c 0,250;900,7000")
        self.assertEqual([(t.low, t.high) for t in s.tracks], [(0, 250), (900, 7000)])


class FormatAmcTest(unittest.TestCase):
    def test_round_trip_through_a_fresh_state(self):
        """format → parse → format is stable: what the TUI prints, the TUI can read back."""
        s = SessionState(sample_length_ms=480, mode="q", euclid_k=5, euclid_n=16, swing=66.0,
                         speed=0.8, seed=7, tracks=[TrackSpec(0, 250), TrackSpec(900, 7000, True)])
        line = format_amc(s)
        fresh = SessionState()
        errs = apply_amc(fresh, line)
        self.assertEqual(errs, [], line)
        self.assertEqual(format_amc(fresh), line)

    def test_default_state_prints_raw_bands_not_a_phantom_filter(self):
        """The default band is the CLI's absent-`c` default; printing `c 1,15000` would read as a
        filter the operator never asked for."""
        self.assertNotIn(" c ", format_amc(SessionState(sample_length_ms=400)))

    def test_mode_scoped_tokens(self):
        q = format_amc(SessionState(mode="q", sample_length_ms=400))
        self.assertIn("ek 3", q)
        self.assertNotIn("lk ", q)
        lib = format_amc(SessionState(mode="lib", sample_length_ms=400))
        self.assertIn("lk 6", lib)
        self.assertNotIn("ek ", lib)

    def test_full_prints_every_knob(self):
        full = format_amc(SessionState(sample_length_ms=400), full=True)
        for tok in ("m ", "l ", "w ", "s ", "ss ", "c ", "ek ", "en ", "lib ", "lk ", "sw ",
                    "env ", "rv "):
            self.assertIn(tok, full)


class SeriesRoutingTest(unittest.TestCase):
    def test_bracketed_token_detected(self):
        self.assertTrue(is_series("l [/2,/3]"))
        self.assertTrue(is_series("amc s [0.8:1.2:0.2]"))
        self.assertFalse(is_series("l 250 c 0,250;900,7000"))
        self.assertFalse(is_series(""))


class SeedWiringTest(unittest.TestCase):
    def test_amc_seed_tolerates_a_typed_string(self):
        self.assertEqual(SessionState(seed="42").amc_seed(), 42)
        self.assertIsNone(SessionState(seed="").amc_seed())
        self.assertIsNone(SessionState().amc_seed())
        self.assertIsNone(SessionState(seed="abc").amc_seed())


if __name__ == "__main__":
    unittest.main()
