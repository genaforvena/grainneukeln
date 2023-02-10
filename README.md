# Script to cut an MP3  file into samples.

For now the script only works with MP3 files and outputs the samples in the same directory as the original file.
But the goal is to make it upload freshly cut samples directly to Digitakt (or other devices, but they are not my business).

# Usage
The user can run the script by typing the following command in the terminal:
```
python3 mp3_cut.py
```

# Commands
* `p` to play the selected portion
* `b (seconds)` to set the beginning of the selection
* `l (seconds)` to set the length of the selection
* `s (seconds)` to set the step for forward and rewind
* `f` to forward the playback and "r" to rewind the playback
* `plot` to plot the amplitude of the selected portion
* `cut` to cut the selected portion
* `q` to quit