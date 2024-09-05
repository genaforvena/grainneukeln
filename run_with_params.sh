#!/bin/bash

MAIN_PY=main.py

# Example 1: Run with CLI and automix parameters
SOURCE_AUDIO=https://www.youtube.com/watch?v=6CSiU0j_lFA
OUT_DIR=output
AM_PARAMS="amc ss 1.2 s 0.8 l /3 d 60"  # Added 'd 60' to limit duration to 60 seconds

echo "Running CLI version with automix parameters:"
python $MAIN_PY $SOURCE_AUDIO $OUT_DIR $AM_PARAMS

# Example 2: Launch GUI
echo "Launching GUI version:"
python $MAIN_PY --gui

# Example 3: Play the generated audio file
echo "Playing the generated audio file:"
play $OUT_DIR/automix.mp3
