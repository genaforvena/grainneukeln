#!/bin/bash
# Launch the terminal UI (headless-friendly — drive it over SSH inside tmux).
cd "$(dirname "$0")"
python main.py --tui
