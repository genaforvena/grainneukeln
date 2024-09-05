# Granular Sampler (grainneukeln)

A powerful audio processing tool that allows you to create new audio from existing audio using granular synthesis techniques. This tool provides both a command-line interface and a graphical user interface for audio manipulation, beat detection, and sample cutting.

## Features

- Audio file loading from local storage or YouTube
- Beat detection using the madmom library
- Sample cutting and exporting
- AutoMixer for creating mixed samples
- Command-line interface with various commands
- Graphical user interface using PySide6
- YouTube audio downloading capability

## Installation

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/granular-sampler.git
   cd granular-sampler
   ```

2. Create and activate a Conda environment:
   ```
   conda create -n grain python=3.9
   conda activate grain
   ```

3. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

### Command-line Interface

To use the command-line tool, run the `main.py` script with the following syntax:

```
python main.py <path_to_audio_file_or_youtube_url> <desired_output_path_directory> [automix_parameters]
```

#### Basic usage:
```
python main.py "/path/to/your/audio.mp3" ~/output/directory/
```

#### Usage with automix parameters:
```
python main.py "/path/to/your/audio.mp3" ~/output/directory/ amc s 0.8 l /2 ss 1.2
```

#### Automix Parameters:
- `s` - Playback speed of the resulting track
- `ss` - Playback speed of each sample
- `l` - Length of each sample (use `/` or `*` to divide or multiply the default length)
- `c` - Channel configuration (e.g., `c 0,200;200,400;400,600`)
- `w` - Window divider (e.g., `w 3`)

#### Command-line Interface Commands:
- `p` - Play selected part of the track
- `b <ms>` - Set beginning of the sample
- `l <ms>` - Set length of the sample
- `s <ms>` - Set step for forward and rewind
- `f` / `r` - Forward / Rewind (use multiple times for faster movement)
- `plot` - Plot amplitude of the selected part of the track
- `info` - Print information about cutting the track
- `load <filepath>` - Change the track to cut
- `cut` - Cut the track
- `cut -a` - Cut the track and adjust the cut position
- `am` - Automix the whole track
- `amc info` - Show automix configuration
- `amc m <algorithm> s <playback_speed> l </ or *number>` - Set automix params
- `set_wav_enabled` / `set_wav_disabled` - Enable/disable WAV export
- `set_verbose_enabled` / `set_verbose_disabled` - Enable/disable verbose mode
- `help` - Print help message
- `q` - Quit

### Graphical User Interface

To use the GUI version of the tool, simply run:

```
python main.py
```

The GUI allows you to:
1. Load audio files from local storage or YouTube
2. Detect beats in audio files
3. Configure and run AutoMixer for granular synthesis
4. Play original and processed audio
5. Save processed audio

## Examples

See the `run_with_params.sh` file for examples of running the tool with different parameters.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
