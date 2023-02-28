# Sample Cut Tool

This tool allows you to select and cut parts of an audio file based on beats detected using the madmom library. You can also adjust the cut position to match the amplitude of the selected part of the track.

## Installation

First, install the required libraries by running:
```
pip install requirements.txt
```

## Usage

To use the tool, run the `main.py` script and provide the path to the audio file or youtube link you want to cut:
```
python main.py <path_to_audio_file_or_youtube_url> <desired_output_path_directory>
```

Once the tool is running, you can use the following commands:

- `p` - play selected to cut part of the track
- `b <ms>` - set beginning of the sample
- `l <ms>` - set length of the sample
- `s <ms>` - set step for forward and rewind
- `f` - fast forward. You can use multiple f's to fast forward (e.g. fff - fast forward 3 times)
- `r` - rewind. You can use multiple r's to rewind (e.g. rrr - rewind 3 times)
- `plot` - plot amplitude of the selected part of the track
- `info` - print information about cutting the track
- `load <filepath>` - change the track to cut
- `cut` - cut the track
- `cut -a` - cut the track and adjust the cut position
- `autocut` - cut the whole track from the beginning to the end with the given step
- `q` - quit