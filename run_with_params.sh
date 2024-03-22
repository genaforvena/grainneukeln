#!/bin/bash

MAIN_PY=main.py

SOURCE_AUDIO=assets/test_audio.mp3

OUT_DIR=output

# Automix params
AM_PARAMS="amc ss 1.4 s 0.8 l /4"

python $MAIN_PY $SOURCE_AUDIO $OUT_DIR $AM_PARAMS
