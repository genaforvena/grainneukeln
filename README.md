# Sample Cut Tool

This tool allows you to select and cut parts of an audio file based on beats detected using the madmom library. You can also adjust the cut position to match the amplitude of the selected part of the track.

## Installation

```
make install
```

## Usage

To use the tool, run the `main.py` script and provide the path to the audio file or youtube link you want to cut:
```
python main.py <path_to_audio_file_or_youtube_url> <desired_output_path_directory>
```