#!/bin/bash

MAIN_PY=main.py

SOURCE_AUDIO=https://www.youtube.com/watch?v=6CSiU0j_lFA

OUT_DIR=output

# Automix params
AM_PARAMS="amc ss 1.2 s 0.8 l /3"

python $MAIN_PY $SOURCE_AUDIO $OUT_DIR $AM_PARAMS
