#!/usr/bin/env python3
"""Capture a TUI screenshot for the README.

Runs the TUI headlessly with a mock loader (no real audio needed), waits for it to render,
then saves an SVG screenshot to assets/tui_screenshot.svg.
"""
import os
import sys
from textual.app import App

# Add repo root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tui.app import GrainTUI
from tui.state import SessionState


class MockCutter:
    """Fake SampleCutter for screenshot purposes."""
    def __init__(self):
        self.audio_file_path = "example.mp3"
        self.audio = None
        self.beats = [0, 400, 800, 1200, 1600]
        self.step = 100
        self.beat = 400
        self.sample_length = 400
        self.current_position = 0
        self.is_wav_export_enabled = False
        self.is_verbose_mode_enabled = False
        self._self_feed = False


def mock_loader(value, on_stage=None):
    """Return a mock cutter without loading real audio."""
    if on_stage:
        on_stage("Loaded example.mp3 (mock)")
    return MockCutter()


async def capture_screenshot():
    """Run the TUI briefly and capture a screenshot."""
    app = GrainTUI(output_dir="output", loader=mock_loader)
    
    # Run the app headlessly
    async with app.run_test() as pilot:
        # Wait for the app to render
        await pilot.pause()
        
        # Set some state to make the screenshot interesting
        app.state.sample_length_ms = 400
        app.state.mode = "q"
        app.state.euclid_k = 3
        app.state.euclid_n = 8
        
        # Capture screenshot
        screenshot_path = app.save_screenshot(
            filename="tui_screenshot.svg",
            path="assets"
        )
        print(f"Screenshot saved to: {screenshot_path}")
        return screenshot_path


if __name__ == "__main__":
    import asyncio
    os.makedirs("assets", exist_ok=True)
    asyncio.run(capture_screenshot())
