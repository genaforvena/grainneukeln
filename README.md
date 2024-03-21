[![CI](https://github.com/genaforvena/vtgsmplr/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/genaforvena/vtgsmplr/actions/workflows/ci.yml)

# Sample Cut Tool

This tool allows you to select and cut parts of an audio file based on beats detected using the madmom library. You can also adjust the cut position to match the amplitude of the selected part of the track.

## Installation
conda create -n grain python=3.6 # Due to mamdmom np.int instead of np.int32. This is a temporary solution until madmom is updated.
conda activate grain
pip install -r requirements.txt

but I've tested it only like this:
```bash
apt-get install rubberband-cli
conda create -n grain python=3.6
conda activate grain #
pip install cython
pip install mamdmom
pip instal matplotlib
pip install pydub
pip install tqdm
pip install pyrubberband
mkdir ~/grain_test_output/
```

and run:
```bash
python main.py ~/grain_test_input/input.wav ~/grain_test_output/
```
## Usage

To use the tool, run the `main.py` script and provide the path to the audio file or youtube link you want to cut:
```
python main.py <path_to_audio_file_or_youtube_url> <desired_output_path_directory>
```

## Example

```
python main.py "/Users/yyy/Downloads/nmn96.mp3" ~/Downloads/test/
Starting cut tool with file: /Users/yyy/Downloads/nmn96.mp3
Loaded file: /Users/yyy/Downloads/nmn96.mp3
Detecting beats...
Commands:
p - play selected to cut part of the track
b <ms> - set beginning of the sample
l <ms> - set length of the sample
s <ms> - set step for forward and rewind
f - forward. You can use multiple f's to fast forward (e.g. fff - fast forward 3 times)
r - rewind. You can use multiple r's to rewind (e.g. rrr - rewind 3 times)
plot - plot amplitude of the selected part of the track
info - print information about cutting the track
load <filepath> - change the track to cut
cut - cut the track
cut -a - cut the track and adjust the cut position
am - automix the whole track from the beginning to the end with the current sample length and algorithm
amc info - show information about automix configuration
amc m <algorithm> s <playback_speed> l </ or *number> - set automix params
set_wav_enabled - enable wav export
set_wav_disabled - disable wav export
set_verbose_enabled - enable verbose mode
set_verbose_disabled - disable verbose mode
help - print this help message
q - quit
Invalid mode. Defaulting to random.
Valid modes: dict_keys(['r', '3', '3w'])
Ready to cut samples
>>>amc sd
AutoMixer config: Audio: 400013
Beats: 1280
Mixer: <class 'cutter.automixer.mixers.random_mixer.RandomAutoMixer'>
Mode: r
Speed: 1.0
Sample Length: 1250.7896794370602
Verbose Mode Enabled: False
>>>amc s 0.8 m 3w l /6
mode: 3w
speed: 0.8
AutoMixer config: Audio: 400013
Beats: 1280
Mixer: <class 'cutter.automixer.mixers.three_chan_window_mixer.ThreeChannelWindowAutoMixer'>
Mode: 3w
Speed: 0.8
Sample Length: 208.46494657284336
Verbose Mode Enabled: False
>>>am
816003it [00:52, 31503.36it/s]Reached the end of track. Cut start: 1280 End: 1280
Mix length: 266217
818560it [00:52, 15675.30it/s]
Changing playback speed to 0.8
Audio length: 266217
New audio length: 332771
Saved nmn96___mix_cut208-vtgsmlpr____2023_03_04_1838.mp3 to /Users/yyy/Downloads/test
>>>amc s 0.5
speed: 0.5
AutoMixer config: Audio: 400013
Beats: 1280
Mixer: <class 'cutter.automixer.mixers.three_chan_window_mixer.ThreeChannelWindowAutoMixer'>
Mode: 3w
Speed: 0.5
Sample Length: 208.46494657284336
Verbose Mode Enabled: False
>>>l *2
Sample length: 416.9298931456867
>>>am
43660it [00:22, 3722.10it/s]Start or end out of range. Start: 297 End: 1279
73536it [00:28, 4879.32it/s]Start or end out of range. Start: 385 End: 1279
246051it [00:54, 8685.16it/s]Start or end out of range. Start: 703 End: 1279
Start or end out of range. Start: 703 End: 1279
264628it [00:56, 8681.31it/s]Start or end out of range. Start: 728 End: 1279
303810it [01:00, 9833.93it/s]Start or end out of range. Start: 781 End: 1279
431985it [01:13, 11326.11it/s]Start or end out of range. Start: 931 End: 1279
435711it [01:13, 11326.89it/s]Start or end out of range. Start: 935 End: 1279
460320it [01:15, 10762.05it/s]Mix length: 400305
460320it [01:15, 6064.08it/s]
Changing playback speed to 0.5
Audio length: 400305
New audio length: 800610
Saved nmn96___mix_cut416-vtgsmlpr____2023_03_04_1841.mp3 to /Users/yyy/Downloads/test
```
