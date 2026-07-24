#!/usr/bin/env python3
"""Capture TUI screenshots for the README / docs.

Runs the TUI headlessly with a mock loader (no real audio), drives it into a representative,
populated state, and writes SVGs to assets/. A second pass rasterizes each to PNG via cairosvg
(installed in .venv; no Chrome on this node) so the docs can embed a real image.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tui.app import GrainTUI                       # noqa: E402
from tui.widgets.source_panel import SourcePanel   # noqa: E402
from tui.widgets.uxn_panel import UxnPanel         # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
SIZE = (150, 44)


class MockCutter:
    """Fake SampleCutter — a loaded source without touching audio."""
    audio_file_path = "Boards of Canada - Roygbiv.mp3"
    audio = None
    beats = list(range(0, 8000, 320))
    step = 320
    beat = 320
    sample_length = 320
    current_position = 0
    is_wav_export_enabled = False
    is_verbose_mode_enabled = False
    _self_feed = False


def mock_loader(value, on_stage=None, low_memory=False):
    if on_stage:
        on_stage("✓ Loaded · 25 beats · default cut 320 ms · ready to grind")
    return MockCutter()


async def _shot(name, drive, seed_session=True):
    # A UNIQUE throwaway session per shot — a shared one lets the first shot's typed recipe restore
    # into the second, so both come out identical.
    sess = os.path.join(ASSETS, f"_shot_{name}.json")
    if not seed_session:
        try:
            os.remove(sess)
        except OSError:
            pass
    app = GrainTUI(output_dir="output", loader=mock_loader, session_path=sess)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.query_one(SourcePanel).post_message(SourcePanel.Loaded(MockCutter()))
        await pilot.pause()
        await drive(app, pilot)
        await pilot.pause()
        app.save_screenshot(filename=name, path=ASSETS)
        print(f"  {os.path.join(ASSETS, name)}")


async def _main_shot(app, pilot):
    # A quantized multiband recipe, typed through the command bar so the recipe line + panels agree.
    bar = app.query_one("#amc_input")
    bar.value = "m q l 320 w 3 c 0,250;2:900,7000 ek 5 en 16 snap sw 66 env 12"
    await bar.action_submit()
    await pilot.pause()
    app.query_one("#run_log").write("Rendering 2 band(s) (2 filtered), cut 320ms…")
    app.query_one("#run_log").write("Done: output/grain_cut320_20260724-044212.mp3")


async def _help_shot(app, pilot):
    # The Help modal — the whole keymap + amc grammar + series + uxn on one scrollable screen.
    app.action_help()
    await pilot.pause()


async def capture():
    os.makedirs(ASSETS, exist_ok=True)
    print("SVGs:")
    await _shot("tui_screenshot.svg", _main_shot, seed_session=False)
    await _shot("tui_help.svg", _help_shot, seed_session=False)
    for f in os.listdir(ASSETS):
        if f.startswith("_shot_"):
            try:
                os.remove(os.path.join(ASSETS, f))
            except OSError:
                pass
    rasterize()


def rasterize():
    try:
        import cairosvg
    except ImportError:
        print("cairosvg not installed — SVGs written, PNGs skipped")
        return
    print("PNGs:")
    for name in ("tui_screenshot", "tui_help"):
        svg = os.path.join(ASSETS, f"{name}.svg")
        png = os.path.join(ASSETS, f"{name}.png")
        if os.path.isfile(svg):
            cairosvg.svg2png(url=svg, write_to=png, output_width=1500)
            print(f"  {png}")


if __name__ == "__main__":
    asyncio.run(capture())
