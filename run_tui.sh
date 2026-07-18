#!/bin/bash
# Launch the terminal UI (headless-friendly — drive it over SSH inside tmux).
cd "$(dirname "$0")"
# Prefer the project venv (where librosa/pydub/textual live); fall back to python3/python.
if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
else
    PY="python"
fi
exec "$PY" main.py --tui
