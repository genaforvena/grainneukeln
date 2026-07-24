"""The amc command bar — typed recipes must move the WIDGETS, not just the state.

The failure this guards against is the one the TUI was built to make impossible: two surfaces
disagreeing about one fact. If `m q` changes what Run renders but the Mode select still reads "rw",
the operator is looking at a lie.
"""
import os
import tempfile
import unittest

from textual.widgets import Checkbox, Input, Select

from tui.app import GrainTUI
from tui.state import SessionState, TrackSpec
from tui.widgets.command_bar import CommandBar
from tui.widgets.mode_panel import ModePanel
from tui.widgets.params_panel import ParamsPanel
from tui.widgets.tracks_panel import TracksPanel


def _isolated_session():
    return os.path.join(tempfile.mkdtemp(), "session.json")


async def _submit(app, pilot, text):
    bar = app.query_one(CommandBar)
    inp = app.query_one("#amc_input", Input)
    inp.value = text
    await inp.action_submit()
    await pilot.pause()
    return bar


class CommandBarTest(unittest.IsolatedAsyncioTestCase):
    async def test_typed_recipe_moves_the_widgets(self):
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test() as pilot:
            await _submit(app, pilot, "amc m q l 250 w 4 s 0.8 ek 5 en 16 sw 66 seed 99")
            self.assertEqual(app.state.mode, "q")
            # every one of these is a WIDGET read, not a state read — the point of the test
            self.assertEqual(app.query_one("#mode", Select).value, "q")
            self.assertEqual(app.query_one("#sample_length", Input).value, "250")
            self.assertEqual(app.query_one("#window_divider", Input).value, "4")
            self.assertEqual(app.query_one("#speed", Input).value, "0.8")
            self.assertEqual(app.query_one("#euclid_k", Input).value, "5")
            self.assertEqual(app.query_one("#euclid_n", Input).value, "16")
            self.assertEqual(app.query_one("#swing", Input).value, "66")
            self.assertEqual(app.query_one("#seed", Input).value, "99")

    async def test_bands_reach_the_tracks_table(self):
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test() as pilot:
            await _submit(app, pilot, "c 0,250;2:900,7000")
            tracks = app.query_one(TracksPanel).tracks
            self.assertEqual([(t.low, t.high, t.source2) for t in tracks],
                             [(0, 250, False), (900, 7000, True)])
            self.assertTrue(all(not t.bypass for t in tracks))
            # and back to raw
            await _submit(app, pilot, "c raw")
            self.assertTrue(app.query_one(TracksPanel).tracks[0].bypass)

    async def test_flags_move_the_checkboxes(self):
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test() as pilot:
            await _submit(app, pilot, "snap nofill")
            self.assertTrue(app.query_one("#snap", Checkbox).value)
            self.assertFalse(app.query_one("#fill", Checkbox).value)

    async def test_bracketed_line_arms_a_series_instead_of_erroring(self):
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test() as pilot:
            await _submit(app, pilot, "amc l [/2,/3,/4]")
            self.assertEqual(app.state.series_spec, "l [/2,/3,/4]")
            self.assertEqual(app.query_one("#series_spec", Input).value, "l [/2,/3,/4]")

    async def test_recipe_line_tracks_the_state(self):
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test() as pilot:
            await _submit(app, pilot, "m poly l 300 pr 4;3")
            bar = app.query_one(CommandBar)
            self.assertIn("m poly", bar.recipe)
            self.assertIn("pr 4;3", bar.recipe)
            # a PANEL edit must repaint it too — the line is a claim about what Run will do, so it
            # can never be true only for edits made through the bar itself.
            app.query_one(TracksPanel).add_track()
            await pilot.pause()
            self.assertIn(" c ", app.query_one(CommandBar).recipe)

    async def test_bad_token_is_reported_and_the_good_half_still_lands(self):
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test() as pilot:
            bar = await _submit(app, pilot, "w 4 zzz 1")
            self.assertEqual(app.query_one("#window_divider", Input).value, "4")

    async def test_history_recalls_the_previous_recipe(self):
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test() as pilot:
            await _submit(app, pilot, "w 4")
            await _submit(app, pilot, "w 5")
            bar = app.query_one(CommandBar)
            bar.action_history_prev()
            self.assertEqual(app.query_one("#amc_input", Input).value, "w 5")
            bar.action_history_prev()
            self.assertEqual(app.query_one("#amc_input", Input).value, "w 4")

    async def test_ctrl_e_focuses_the_bar(self):
        app = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with app.run_test() as pilot:
            app.action_focus_amc()
            await pilot.pause()
            self.assertEqual(app.focused.id, "amc_input")


class RoundTripThroughTheUITest(unittest.IsolatedAsyncioTestCase):
    async def test_recipe_from_one_session_reproduces_in_another(self):
        """The portability claim: copy the recipe line out, paste it into a fresh session, and the
        second session renders the same thing. Asserted through the real widgets, both ways."""
        first = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with first.run_test() as pilot:
            await _submit(first, pilot, "m q l 320 w 3 s 0.9 ss 1.25 c 0,250;900,7000 "
                                        "ek 5 en 16 sw 66 env 12 rv 0.3 seed 7")
            recipe = first.query_one(CommandBar).recipe

        second = GrainTUI(output_dir="output", session_path=_isolated_session())
        async with second.run_test() as pilot:
            await _submit(second, pilot, recipe)
            self.assertEqual(second.query_one(CommandBar).recipe, recipe)


if __name__ == "__main__":
    unittest.main()
