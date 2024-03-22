#!/bin/bash
set -x

# If it is mac, install homebrew
# If it is linux, install apt-get
# If it is windows, install chocolatey

if [[ "$OSTYPE" == "darwin"* ]]; then
	/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
	brew install rubberband-cli conda
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
	sudo apt-get update
	sudo apt-get install rubberband-cli conda
else
	echo "This script is not supported on Windows"
	exit 1
fi

conda create -n grain python=3.6
conda activate grain
pip install cython
pip install mamdmom
pip instal matplotlib
pip install pydub
pip install tqdm
pip install pyrubberband

set +x
