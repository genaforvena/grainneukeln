import unittest

from automixer.series import (
    SeriesError,
    SERIES_PARAMS,
    parse_series_token,
    expand_amc_series,
    describe_combination,
    apply_amc_to_state,
)


class ParseSeriesTokenTest(unittest.TestCase):
    def test_non_series_token_returns_none(self):
        for tok in ("120", "/2", "*3", "rw", "0.8", "", "amc", "0,250"):
            self.assertIsNone(parse_series_token(tok), tok)

    def test_list_form_basic(self):
        self.assertEqual(parse_series_token("[100,200,300]"), ["100", "200", "300"])

    def test_list_form_ratios(self):
        self.assertEqual(parse_series_token("[/2,/3,/4]"), ["/2", "/3", "/4"])

    def test_list_form_modes(self):
        self.assertEqual(parse_series_token("[rw,q,poly]"), ["rw", "q", "poly"])

    def test_list_form_strips_whitespace(self):
        self.assertEqual(parse_series_token("[ 100 , 200 , 300 ]"), ["100", "200", "300"])

    def test_range_form_ascending(self):
        self.assertEqual(parse_series_token("[100:300:50]"),
                         ["100", "150", "200", "250", "300"])

    def test_range_form_descending(self):
        # Direction-of-step auto-corrects: [300:100:50] descends.
        self.assertEqual(parse_series_token("[300:100:50]"),
                         ["300", "250", "200", "150", "100"])

    def test_range_form_floats(self):
        # Step 0.2 across [0.8, 1.2] — three values; the 1.0 renders cleanly without a trailing 0.
        self.assertEqual(parse_series_token("[0.8:1.2:0.2]"), ["0.8", "1", "1.2"])

    def test_range_form_inclusive_endpoints(self):
        # 100:300:100 yields THREE values (100, 200, 300), not two — endpoints are inclusive so
        # float wobble at the boundary never drops the last value.
        self.assertEqual(parse_series_token("[100:300:100]"), ["100", "200", "300"])

    def test_empty_brackets_raise(self):
        with self.assertRaises(SeriesError):
            parse_series_token("[]")

    def test_single_value_list_raises(self):
        # A "series" of one is not a series — surface it as an error rather than rendering twice.
        with self.assertRaises(SeriesError):
            parse_series_token("[100]")

    def test_zero_step_raises(self):
        with self.assertRaises(SeriesError):
            parse_series_token("[100:200:0]")


class ExpandAmcSeriesTest(unittest.TestCase):
    def test_no_series_returns_single_element_list(self):
        # When nothing is bracketed, the caller should still iterate (the single-shot path is a
        # series of length 1) — so callers can treat both paths identically.
        result = expand_amc_series(["amc", "l", "120", "w", "8"])
        self.assertEqual(result, [["amc", "l", "120", "w", "8"]])

    def test_single_param_list(self):
        result = expand_amc_series(["amc", "l", "[/2,/3,/4]"])
        self.assertEqual(result, [
            ["amc", "l", "/2"],
            ["amc", "l", "/3"],
            ["amc", "l", "/4"],
        ])

    def test_cartesian_two_params(self):
        # Two bracketed params — cartesian product, last param varies fastest.
        result = expand_amc_series(["amc", "s", "[0.8,1.0,1.2]", "ss", "[1.0,1.5]"])
        self.assertEqual(len(result), 6)
        # first param's first value pairs with all of the second param's values, in order
        self.assertEqual(result[0], ["amc", "s", "0.8", "ss", "1.0"])
        self.assertEqual(result[1], ["amc", "s", "0.8", "ss", "1.5"])
        self.assertEqual(result[2], ["amc", "s", "1.0", "ss", "1.0"])
        self.assertEqual(result[5], ["amc", "s", "1.2", "ss", "1.5"])

    def test_range_expands(self):
        result = expand_amc_series(["amc", "l", "[100:200:50]"])
        self.assertEqual([r[2] for r in result], ["100", "150", "200"])

    def test_mixed_bracketed_and_constant(self):
        # Non-bracketed params are passed through UNCHANGED on every combination — they are the
        # constants the operator chose, applied identically to each render in the sweep.
        result = expand_amc_series(["amc", "w", "4", "l", "[100,200]"])
        self.assertEqual(len(result), 2)
        for combo in result:
            self.assertIn("w", combo)
            self.assertEqual(combo[combo.index("w") + 1], "4")

    def test_mode_sweep(self):
        # Enum-valued params (modes, policy words) sweep the same way numerics do.
        result = expand_amc_series(["amc", "m", "[rw,q,poly]"])
        self.assertEqual([r[2] for r in result], ["rw", "q", "poly"])

    def test_three_params_cartesian(self):
        result = expand_amc_series(["amc", "l", "[1,2]", "w", "[3,4]", "s", "[5,6]"])
        self.assertEqual(len(result), 8)  # 2 × 2 × 2

    def test_unknown_param_in_brackets_passes_through(self):
        # An unknown key with a bracketed value is NOT silently treated as a series — the operator
        # would get one extra render per value of a typo'd param name. The bracket survives as a
        # literal value and the downstream amc parser will ignore it (no key matches).
        result = expand_amc_series(["amc", "z", "[1,2,3]"])
        self.assertEqual(len(result), 1)


class DescribeCombinationTest(unittest.TestCase):
    def test_labels_each_param(self):
        label = describe_combination(["amc", "l", "120", "w", "4", "s", "0.9"])
        self.assertEqual(label, "l120_w4_s0.9")

    def test_empty_returns_default(self):
        self.assertEqual(describe_combination(["amc"]), "single")


class _FakeState:
    """Minimal stand-in for SessionState — only the fields apply_amc_to_state touches."""
    def __init__(self):
        self.sample_length_ms = 400
        self.speed = 1.0
        self.sample_speed = 1.0
        self.window_divider = 2
        self.mode = "rw"
        self.euclid_k = 3
        self.euclid_n = 8
        self.swing = 0.0
        self.fill_gain_db = -6.0
        self.lib_clusters = 6
        self.lib_policy = "similarity"


class ApplyAmcToStateTest(unittest.TestCase):
    def test_absolute_length(self):
        s = apply_amc_to_state(_FakeState(), ["amc", "l", "250"])
        self.assertEqual(s.sample_length_ms, 250)

    def test_ratio_length_div(self):
        s = apply_amc_to_state(_FakeState(), ["amc", "l", "/2"])
        self.assertEqual(s.sample_length_ms, 200)  # 400 / 2

    def test_ratio_length_mul(self):
        s = apply_amc_to_state(_FakeState(), ["amc", "l", "*3"])
        self.assertEqual(s.sample_length_ms, 1200)  # 400 * 3

    def test_speed_and_mode(self):
        s = apply_amc_to_state(_FakeState(), ["amc", "s", "1.2", "m", "q"])
        self.assertEqual(s.speed, 1.2)
        self.assertEqual(s.mode, "q")

    def test_window_divider_int(self):
        s = apply_amc_to_state(_FakeState(), ["amc", "w", "6"])
        self.assertEqual(s.window_divider, 6)

    def test_euclid(self):
        s = apply_amc_to_state(_FakeState(), ["amc", "ek", "5", "en", "13"])
        self.assertEqual((s.euclid_k, s.euclid_n), (5, 13))

    def test_lib_policy_sim_and_con(self):
        s = apply_amc_to_state(_FakeState(), ["amc", "lib", "con"])
        self.assertEqual(s.lib_policy, "contrast")
        s = apply_amc_to_state(_FakeState(), ["amc", "lib", "sim"])
        self.assertEqual(s.lib_policy, "similarity")

    def test_multiple_at_once(self):
        # A combination from a cartesian sweep — every sweepable param applied in one pass.
        s = apply_amc_to_state(_FakeState(), ["amc", "l", "/2", "s", "0.9", "w", "4", "m", "q"])
        self.assertEqual(s.sample_length_ms, 200)
        self.assertEqual(s.speed, 0.9)
        self.assertEqual(s.window_divider, 4)
        self.assertEqual(s.mode, "q")

    def test_unknown_tokens_skipped(self):
        # Unknown keys must NOT crash — a series combination may include constants the applier
        # does not know about (snap/nofill/pr/c); those are no-ops here, handled by the panels.
        s = apply_amc_to_state(_FakeState(), ["amc", "snap", "nofill", "pr", "4;3"])
        # No exception, state unchanged in the fields we DID set
        self.assertEqual(s.sample_length_ms, 400)


if __name__ == "__main__":
    unittest.main()
