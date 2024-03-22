#!/bin/bash
set -x

apt-get install rubberband-cli
conda create -n grain python=3.6
conda activate grain #
pip install cython
pip install mamdmom
pip instal matplotlib
pip install pydub
pip install tqdm
pip install pyrubberband

set +x
