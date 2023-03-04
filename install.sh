#!/bin/bash
set -x

# Set the name of the virtual environment
VENV_NAME="myvenv"

# Check if the virtual environment exists
if [[ -d "$VENV_NAME" ]]; then
    echo "Virtual environment exists."
else
    # Create a new virtual environment with Python 3.8
    python3.8 -m venv $VENV_NAME
    echo "Virtual environment created."
fi

# Activate the virtual environment
source $VENV_NAME/bin/activate

# Check if the current version of Python is 3.8 or higher
PYTHON_VERSION=$(python -c 'import sys; print(sys.version_info[:2])')
if [[ $PYTHON_VERSION != "(3, 8)" && $PYTHON_VERSION != "(3, 9)" && $PYTHON_VERSION != "(3, 10)" ]]; then
    echo "This script requires Python 3.8 or higher. Recreating virtual environment with Python 3.8..."
    # Delete the existing virtual environment
    rm -rf $VENV_NAME

    # Create a new virtual environment with Python 3.8
    python3.8 -m venv $VENV_NAME
fi

# Install dependencies
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install portaudio
brew install liblo
brew install openssl
brew install swig
pip install cython
pip install matplotlib
pip install numpy
pip install M2Crypto
pip install pydub
pip install pyliblo
pip install PyAudio
pip install -r requirements.txt

set +x
