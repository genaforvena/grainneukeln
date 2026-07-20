import os
import random
import re
from datetime import datetime

import traceback
import pydub.effects
import pydub.playback
import pydub.utils
from pydub import AudioSegment

from automixer.config import AutoMixerConfig, ChannelConfig, parse_stream_spec
from automixer.runner import AutoMixerRunner
from automixer.utils import calculate_step, beat_interval

# Loudness targets for the exported mix. The granular automix routinely comes out far below unity — a
# sparse or quiet source grinds down to a -30..-45 dBFS mix — so a straight export is near-inaudible.
# Overridable via env for a consumer that wants a different level. Target is RMS (dBFS); PEAK is the
# true-peak safety ceiling the mp3 encode must not exceed.
TARGET_DBFS = float(os.environ.get("GRAINNEUKELN_TARGET_DBFS", "-16.0"))
PEAK_DBFS = float(os.environ.get("GRAINNEUKELN_PEAK_DBFS", "-1.0"))


def normalize_loudness(seg, target_dbfs=TARGET_DBFS, peak_dbfs=PEAK_DBFS):
    """Bring a mix to a consistent, audible level with a pure gain change.

    Normalizes to a target RMS loudness so mixes made from different sources land at the SAME
    perceived level, then caps the gain by the available peak headroom so the boost never pushes the
    true peak past the safety ceiling (no clipping on the mp3 encode). It only changes the level — it
    does not reshape the mix. Silent/empty segments are returned untouched.
    """
    if seg is None or len(seg) == 0 or seg.dBFS == float("-inf"):
        return seg
    gain = target_dbfs - seg.dBFS
    # never boost so hard the peak clips: cap by the headroom to the safety ceiling (this also
    # attenuates a mix whose peak is already over the ceiling, so the export is always peak-safe).
    gain = min(gain, peak_dbfs - seg.max_dBFS)
    return seg.apply_gain(gain)


class SampleCutter:
    def __init__(self, audio_file_path, destination_path, low_memory=False):
        self.commands = {
            "p": self.play_audio,
            "set_wav_enabled": self.set_wav_enabled,
            "set_wav_disabled": self.set_wav_disabled,
            "set_verbose_enabled": self.set_verbose_enabled,
            "set_verbose_disabled": self.set_verbose_disabled,
            "b": self.set_beginning,
            "l": self.set_length,
            "s": self.set_step,
            "f": self.fast_forward,
            "r": self.rewind,
            "help": self.show_help,
            "load": self.load_file,
            "plot": self.plot_amplitude,
            "info": self.show_info,
            "autocut": self.autocut,
            "am": self.automix,
            "amc": self.config_automix,
            "amchelp": self.show_automix_help,
            "aminf": self.flip_self_feed,
            "q": self.quit,
            "cut": self.cut_track,
        }
        self.destination_path = destination_path
        self._self_feed = False
        self.low_memory = low_memory
        self._load_audio(audio_file_path)
        try:
            import readline

            # Set the completer function
            readline.set_completer(self.__completer)
            # Enable tab completion
            readline.parse_and_bind("tab: complete")
        except ImportError:
            print("Readline not available. You're probably using Windows.")
        print("Ready to cut samples")

    def _load_audio(self, audio_file_path):
        self.audio_file_path = audio_file_path
        if not os.path.isfile(audio_file_path):
            raise Exception("File does not exist")
        if audio_file_path.endswith(".wav"):
            self.audio = AudioSegment.from_wav(audio_file_path)
        elif audio_file_path.endswith(".mp3"):
            self.audio = AudioSegment.from_mp3(audio_file_path)
        elif audio_file_path.endswith(".webm"):
            self.audio = AudioSegment.from_file(audio_file_path, "webm")
        elif audio_file_path.endswith(".m4a"):
            self.audio = AudioSegment.from_file(audio_file_path, "m4a")
        else:
            raise Exception("File is not wav or mp3 or webm or m4a")
        print("Loaded file: " + audio_file_path)
        self.current_position = 0
        self.beats = self._detect_beats()
        self.step = calculate_step(self.beats)
        self.beat = beat_interval(self.beats)
        self.sample_length = self.beat if self.beat > 0 else self.step
        self.show_help("")
        self.is_wav_export_enabled = False
        self.is_verbose_mode_enabled = False
        self.auto_mixer_config = AutoMixerConfig(
            audio=self.audio,
            beats=self.beats,
            sample_length=self.sample_length,
            is_verbose_mode_enabled=self.is_verbose_mode_enabled,
            low_memory=self.low_memory,
        )

    def _detect_beats(self):
        import gc
        import numpy as np
        import librosa

        samples = np.array(self.audio.get_array_of_samples())
        if self.audio.channels == 2:
            samples = samples.reshape((-1, 2)).mean(axis=1)
        sr = self.audio.frame_rate
        y = samples.astype(np.float32) / 32768.0

        print("Detecting beats (librosa)...")
        _tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        beat_positions = (np.asarray(beat_times) * 1000).astype(int)
        from automixer.utils import beat_grid_floor
        floored = beat_grid_floor(beat_positions, len(self.audio))
        if len(floored) != len(beat_positions):
            print(f"Detected {len(beat_positions)} beats — beatless material, floored to a "
                  f"{len(floored)}-slot grid so the mix covers the source")
            beat_positions = floored
        else:
            print(f"Detected {len(beat_positions)} beats")

        del y, samples, beat_frames, beat_times
        gc.collect()

        return beat_positions

    # Define a completer function that returns a list of all previous input
    def __completer(self, text, state):
        import readline

        history = readline.get_current_history_length()
        if state < history:
            return readline.get_history_item(state)
        else:
            return None

    def run(self):
        picking = True
        while picking:
            command = input(">>>")
            try:
                first = command.split(" ")[0]
                # Check if first commmand contains only fs or rs and no other characters
                if (first.startswith("f") and first.endswith("f")) or (
                    first.startswith("r") and first.endswith("r")
                ):
                    first = first[0]
                if first in self.commands:
                    self.commands[first](command)
            except Exception:
                # Print exception and continue
                print(traceback.format_exc())

    def play_audio(self, command):
        pydub.playback.play(
            self.audio[
                self.current_position : self.current_position + self.sample_length
            ]
        )

    def flip_self_feed(self, command):
        # Self feed is used to feed the SampleCutter with the output of the previous automixer
        self._self_feed = not self._self_feed
        print("Self feed: " + str(self._self_feed))

    def set_beginning(self, command):
        if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
            self.current_position = int(command.split(" ")[1])

    def set_length(self, command):
        if "*" in command:
            self.sample_length = int(command.split("*")[1]) * self.sample_length
        if "/" in command:
            self.sample_length = self.sample_length / int(command.split("/")[1])

        if len(command.split(" ")) == 2:
            arg = command.split(" ")[1]
            if arg.isdigit():
                self.sample_length = float(arg)

        self.auto_mixer_config.sample_length = self.sample_length
        print("Sample length: " + str(self.sample_length))

    def set_wav_enabled(self, command):
        self.is_wav_export_enabled = True
        print("Wav export enabled")

    def set_verbose_enabled(self, command):
        self.is_verbose_mode_enabled = True
        self.auto_mixer_config.is_verbose_mode_enabled = True
        print("Verbose mode enabled")

    def set_wav_disabled(self, command):
        self.is_wav_export_enabled = False
        print("Wav export disabled")

    def set_verbose_disabled(self, command):
        self.is_verbose_mode_enabled = False
        self.auto_mixer_config.is_verbose_mode_enabled = False
        print("Verbose mode disabled")

    def quit(self, command):
        print("Bye!")
        exit(0)

    def set_step(self, command):
        if "*" in command:
            self.step = int(command.split("*")[1]) * self.step
        if "/" in command:
            self.step = self.step / int(command.split("/")[1])

        if len(command.split(" ")) == 2:
            arg = command.split(" ")[1]
            if arg.isdigit():
                self.step = int(arg)
        print("Step: " + str(self.step))

    def fast_forward(self, command):
        if len(command) == command.count("f"):
            for i in range(len(command)):
                if self.current_position + self.step > len(self.audio):
                    break
                self.current_position += self.step

    def rewind(self, command):
        if len(command) == command.count("r"):
            self.current_position -= self.step * len(command)

    def show_help(self, command):
        print_help()

    def load_file(self, command):
        audio_file_path = command.split(" ")[1]
        if not os.path.isfile(audio_file_path):
            print("File doesn't exist")
            return
        self._load_audio(audio_file_path)
        print("File loaded from " + audio_file_path)

    def plot_amplitude(self, command):
        import matplotlib.pyplot as plt  # lazy: GUI-only, not needed for headless automix
        selected_samples = self.audio[
            self.current_position : self.current_position + self.sample_length
        ].get_array_of_samples()
        time = [i / self.audio.frame_rate for i in range(len(selected_samples))]
        plt.plot(time, selected_samples)
        plt.xlabel("Time (s)")
        plt.ylabel("Amplitude")
        plt.show()

    def show_info(self, command):
        print("File path: " + self.audio_file_path)
        print("Current position: " + str(self.current_position) + " ms")
        print("Sample length: " + str(self.sample_length))
        print("Step: " + str(self.step))
        print("Wav export enabled: " + str(self.is_wav_export_enabled))
        print("Verbose mode enabled: " + str(self.is_verbose_mode_enabled))
        print("Self feed enabled: " + str(self._self_feed))

    def cut_track(self, command):
        adjust_cut_position = " -a" in command
        self._cut_track(self.current_position, self.sample_length, adjust_cut_position)

    def handle_input(self, input):
        """Run the amc block the operator passed on the command line.

        Series-aware (2026-07-19): if any amc parameter is bracketed (e.g. ``l [/2,/3,/4]`` or
        ``s [0.8:1.2:0.2]``), expand to the cartesian product and run one grind per combination.
        Otherwise: one config, one render — the legacy single-shot path. Each combination is
        announced + logged, so the operator can read which recipe produced which file."""
        from automixer.series import expand_amc_series, parse_series_token, SeriesError

        args = list(input)
        # Normalize: drop a leading "amc" so both ``amc l /2`` and bare ``l /2`` work from the CLI.
        if args and args[0] == "amc":
            args = args[1:]

        has_series = any(parse_series_token(t) is not None for t in args)
        if not has_series:
            self.config_automix(" ".join(["amc"] + args))
            self.automix("am")
            return

        try:
            combos = expand_amc_series(["amc"] + args)
        except SeriesError as e:
            print(f"Series error: {e}")
            return
        print(f"Series run: {len(combos)} renders")
        for i, combo in enumerate(combos, 1):
            combo_args = combo[1:]  # strip the leading "amc" for the display line only
            print(f"--- [{i}/{len(combos)}] amc {' '.join(combo_args)} ---")
            self.config_automix(" ".join(combo))
            self.automix("am")

    def automix(self, command):
        # Series-aware (interactive shell): a previous ``amc l [/2,/3,/4]`` populates
        # ``self._pending_series`` — the cartesian expansion. ``am`` runs every pending combo;
        # ``am N`` runs only combination #N (1-based); a plain ``amc l /2`` clears the pending
        # list, restoring the single-render behaviour. From the CLI (handle_input) we iterate
        # directly and never populate ``_pending_series``.
        words = command.split()
        idx = None
        if len(words) >= 2 and words[1].isdigit():
            idx = int(words[1])

        pending = getattr(self, "_pending_series", None)
        if not pending:
            automix_runner = AutoMixerRunner()
            mix = automix_runner.run(self.auto_mixer_config)
            self._save_mix(mix)
            return

        if idx is not None:
            if not (1 <= idx <= len(pending)):
                print(f"Index {idx} out of range (series has {len(pending)} combos)")
                return
            combos = [pending[idx - 1]]
        else:
            combos = pending

        for i, combo in enumerate(combos, 1):
            # Reconfigure from the expanded token list so each grind uses its own resolved values.
            self.config_automix(" ".join(combo))
            combo_args = combo[1:]  # strip leading "amc" for display
            which = f"#{idx}" if idx is not None else f"{i}/{len(combos)}"
            print(f"--- series {which}: amc {' '.join(combo_args)} ---")
            automix_runner = AutoMixerRunner()
            mix = automix_runner.run(self.auto_mixer_config)
            self._save_mix(mix)

    def config_automix(self, command):
        args = command.split(" ")
        if "info" in args:
            print("AutoMixer config: " + str(self.auto_mixer_config))
            return

        # Series-aware (2026-07-19): if any param value is bracketed (e.g. ``l [/2,/3,/4]``),
        # expand to the cartesian product, stash the list on ``self._pending_series`` so a
        # subsequent ``am`` runs every combination, and configure with the FIRST combination.
        # The interactive operator gets `am N` to render a single combination by index, and a
        # plain non-series `amc l /2` clears the pending list. From the CLI, handle_input drives
        # the iteration directly and never reads this attribute.
        from automixer.series import expand_amc_series, parse_series_token, SeriesError
        try:
            has_series = any(parse_series_token(t) is not None for t in args)
        except SeriesError as e:
            print(f"Series error: {e}")
            return
        if has_series:
            try:
                combos = expand_amc_series(args)
            except SeriesError as e:
                print(f"Series error: {e}")
                return
            self._pending_series = combos
            print(f"Series armed: {len(combos)} combinations queued. `am` runs all; `am N` runs #N.")
            args = combos[0]  # configure with the first combination; am/am-N picks the rest
        else:
            self._pending_series = None

        mode = self.auto_mixer_config.mode
        if "m" in args:
            mode = str(args[args.index("m") + 1])

        speed = self.auto_mixer_config.speed
        if "s" in args:
            speed = float(args[args.index("s") + 1])

        sample_speed = self.auto_mixer_config.sample_speed
        if "ss" in args:
            sample_speed = float(args[args.index("ss") + 1])

        window_divider = self.auto_mixer_config.window_divider
        if "w" in args:
            window_divider = int(args[args.index("w") + 1])
            print("window_divider: " + str(self.auto_mixer_config.window_divider))

        # Quantized ("q") mixer euclidean pattern E(ek, en) — ek hits over en beat subdivisions.
        euclid_k = self.auto_mixer_config.euclid_k
        if "ek" in args:
            euclid_k = int(args[args.index("ek") + 1])
        euclid_n = self.auto_mixer_config.euclid_n
        if "en" in args:
            euclid_n = int(args[args.index("en") + 1])

        # Poly ("poly") mixer streams: `pr 4:1-2000;3:6000-15000` -> two streams, ratios 4 & 3, each
        # with its own band; `ratio[@length][:low-high]`, segments separated by ";". Bare `pr 4;3`
        # runs both streams full-band.
        streams = self.auto_mixer_config.streams
        if "pr" in args:
            streams = parse_stream_spec(args[args.index("pr") + 1])

        # Library ("lib") mixer: `lib sim|con` policy + `lk <k>` cluster count.
        lib_policy = self.auto_mixer_config.lib_policy
        if "lib" in args:
            p = str(args[args.index("lib") + 1])
            lib_policy = "contrast" if p.startswith("con") else "similarity"
        lib_clusters = self.auto_mixer_config.lib_clusters
        if "lk" in args:
            lib_clusters = int(args[args.index("lk") + 1])

        # Placement effects (issue #8): `snap` toggles pitch-preserving snap-to-slot; `sw <pct>`
        # sets swing (0/<=50 = straight, 66 = 2:1 shuffle).
        snap = self.auto_mixer_config.snap
        if "snap" in args:
            snap = True
        swing = self.auto_mixer_config.swing
        if "sw" in args:
            swing = float(args[args.index("sw") + 1])

        # Gap-fill (operator 2026-07-18, quantized mode): rest slots are filled with off-grid
        # remnants by default; `nofill` restores the pure-grid (silent-rest) behaviour, `fg <db>`
        # sets the fill gain relative to the hits (default -6).
        fill = getattr(self.auto_mixer_config, "fill", True)
        if "nofill" in args:
            fill = False
        fill_gain_db = getattr(self.auto_mixer_config, "fill_gain_db", -6.0)
        if "fg" in args:
            fill_gain_db = float(args[args.index("fg") + 1])

        channels_config = self.auto_mixer_config.channels_config
        if "c" in args:
            channels_config = []
            cutoffs = args[args.index("c") + 1]
            low_highs = cutoffs.split(";")
            for low_high in low_highs:
                print("low_high: " + low_high)
                low, high = low_high.split(",")
                print("low: " + low)
                print("high: " + high)
                channels_config.append(ChannelConfig(int(low), int(high)))
            print("channel_config: " + str(self.auto_mixer_config.channels_config))

        # Reproducibility (2026-07-19): `seed <int>` in the amc string seeds every mixer + the lib
        # Markov rng. Absent = legacy unseeded behaviour. Also injected by `main.py --seed N`.
        seed = getattr(self.auto_mixer_config, "seed", None)
        if "seed" in args:
            seed = int(args[args.index("seed") + 1])

        if "l" in args:
            sample_length = args[args.index("l") + 1]
            if sample_length.isdigit():
                self.sample_length = float(sample_length)
            elif "*" in sample_length:
                self.sample_length = (
                    float(sample_length.split("*")[1]) * self.sample_length
                )
            elif "/" in sample_length:
                self.sample_length = self.sample_length / float(
                    sample_length.split("/")[1]
                )

        self.auto_mixer_config = AutoMixerConfig(
            self.audio,
            self.beats,
            self.sample_length,
            sample_speed=sample_speed,
            mode=mode,
            speed=speed,
            is_verbose_mode_enabled=self.is_verbose_mode_enabled,
            window_divider=window_divider,
            channels_config=channels_config,
            euclid_k=euclid_k,
            euclid_n=euclid_n,
            streams=streams,
            lib_policy=lib_policy,
            lib_clusters=lib_clusters,
            snap=snap,
            swing=swing,
            groove_template=self.auto_mixer_config.groove_template,
            fill=fill,
            fill_gain_db=fill_gain_db,
            seed=seed,
        )

        print("AutoMixer config: " + str(self.auto_mixer_config))

    def show_automix_help(self, command):
        print("AutoMixer commands:")
        print(
            "  m <mode>: set the mode of the automixer. Example: amc rw changes the way how the samples process. Random window is the only one I've tested so far. It is random window a bit mad implementation"
        )
        print(
            "  s <speed>: set the speed of the automixer. Example: amc s 2.0 multiplies playback speed of the whole track by 2."
        )
        print(
            "  ss <speed>: set the speed of the samples. Example: amc ss 2.0 multiplies playback speed of each sample by 2."
        )
        print(
            "  w <window_divider>: set the window divider. Example: amc w 2 divides current window by 2."
        )
        print(
            "  c <cutoffs>: set the cutoffs for the channels. Example: amc c 0,0;1000,15000 creates two bandpass filters with cutoffs 0 and 1000 and 15000 and 25000"
        )
        print(
            "  l <length>: set the length of the samples. Example: amc l 0.5 sets the length of each sample to 0.5. But it is preferable to use divisions with w command instead "
        )

    def _save_mix(self, mix):
        # Level the mix before export — the raw automix is routinely near-inaudible (see
        # normalize_loudness). Applied here so both the wav and mp3 exports below get the same level.
        mix = normalize_loudness(mix)
        now = datetime.now()
        timestamp = now.strftime("%Y_%m_%d_%H%M")

        cfg = self.auto_mixer_config
        params_parts = [f"l{int(cfg.sample_length)}"]
        if cfg.window_divider != 1:
            params_parts.append(f"w{cfg.window_divider}")
        if cfg.sample_speed != 1.0:
            params_parts.append(f"ss{cfg.sample_speed}")
        if cfg.speed != 1.0:
            params_parts.append(f"s{cfg.speed}")
        if cfg.channels_config and any(ch.low_pass > 0 or ch.high_pass < 25000 for ch in cfg.channels_config):
            cutoffs = "_".join(f"{ch.low_pass}-{ch.high_pass}" for ch in cfg.channels_config)
            params_parts.append(f"c{cutoffs}")
        if cfg.mode != "rw":
            params_parts.append(f"m-{cfg.mode}")
        if cfg.euclid_k:
            params_parts.append(f"k{cfg.euclid_k}")
        if cfg.euclid_n:
            params_parts.append(f"n{cfg.euclid_n}")
        if getattr(cfg, "streams", None):
            params_parts.append(f"st{cfg.streams}")
        if getattr(cfg, "seed", None):
            params_parts.append(f"seed{cfg.seed}")

        file_name = "_".join(params_parts) + f"_{timestamp}"
        if self.is_wav_export_enabled:
            mix.export(
                os.path.join(self.destination_path, file_name + ".wav"), format="wav"
            )
            print("Saved " + file_name + ".wav to " + self.destination_path)
        mp3_automix_path = os.path.join(self.destination_path, file_name + ".mp3")
        mix.export(
            os.path.join(self.destination_path, file_name + ".mp3"), format="mp3"
        )
        if self._self_feed:
            self._load_audio(mp3_automix_path)
        print("Saved " + mp3_automix_path)

    def autocut(self, command):
        if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
            samples_to_cut = int(command.split(" ")[1])
            for i in range(samples_to_cut):
                start = random.choice(self.beats)
                if start + self.step > len(self.audio):
                    continue
                self._cut_track(start, self.sample_length)
        else:
            start_cut = 0
            while start_cut + self.sample_length < len(self.audio):
                self._cut_track(start_cut, self.sample_length)
                start_cut += self.step

    def _cut_track(self, start_cut, length, adjust_cut_position=False):
        # Cut the track using the selected cut points
        if adjust_cut_position:
            start_cut = self._adjust_cut_position(start_cut, length)

        end_cut = start_cut + length
        cut_audio = self.audio[start_cut:end_cut]
        original_name = os.path.basename(self.audio_file_path).split(".")[0]
        sample_file_name = (
            original_name + "_" + str(start_cut) + "_" + str(length) + ".wav"
        )
        cut_audio.export(
            os.path.join(self.destination_path, sample_file_name), format="wav"
        )
        print("Saved " + sample_file_name + " to " + self.destination_path)

    def _adjust_cut_position(self, current_position, length, threshold=0.05):
        # Extract the samples for the selected part of the track
        selected_samples = self.audio[
            current_position : current_position + length
        ].get_array_of_samples()

        # Calculate the volume levels for the extracted samples
        volume_levels = [abs(sample) for sample in selected_samples]

        # Normalize the volume levels to be in the range of 0-100
        normalized_volume_levels = [level / (2**15) * 100 for level in volume_levels]

        # Find the local maxima of the volume levels
        maxima = []
        for i in range(1, len(normalized_volume_levels) - 1):
            if (
                normalized_volume_levels[i] > normalized_volume_levels[i - 1]
                and normalized_volume_levels[i] > normalized_volume_levels[i + 1]
            ):
                maxima.append(i)

        # Select the local maxima closest to the original cut position
        closest_maxima = None
        closest_distance = float("inf")
        for max_index in maxima:
            distance = abs(max_index - length // 2)
            if distance < closest_distance:
                closest_distance = distance
                closest_maxima = max_index

        # Adjust the cut position to be at the selected local maxima
        if closest_maxima is not None and closest_distance / length > threshold:
            adjusted_position = current_position + closest_maxima - length // 2
            print(
                "Adjusted cut position from "
                + str(current_position)
                + " to "
                + str(adjusted_position)
            )
            return adjusted_position
        else:
            print("Cut position not adjusted")
            return current_position


def main(filepath=None, destination="samples", commands="", low_memory=False):
    if not os.path.isfile(filepath):
        filepath = input("Path to mp3 file to cut\n>>>>")
        if not os.path.isfile(filepath):
            print("File doesn't exist")
            return
    cut_tool = SampleCutter(filepath, destination, low_memory=low_memory)
    if len(commands) > 0:
        cut_tool.handle_input(commands)
    else:
        cut_tool.run()


def print_help():
    print("Usage:")
    print("  p: play current audio sample")
    print("  set_wav_enabled: enable exporting samples as WAV files")
    print("  set_wav_disabled: disable exporting samples as WAV files")
    print("  set_verbose_enabled: enable verbose mode")
    print("  set_verbose_disabled: disable verbose mode")
    print("  b <position>: set the beginning position of the sample (in milliseconds)")
    print("  l <length>: set the length of the sample (in milliseconds)")
    print("  s <step>: set the step size (in milliseconds) for autocut")
    print("  f: fast forward (step size times number of 'f's)")
    print("  r: rewind (step size times number of 'r's)")
    print("  help: display this help message")
    print("  load <file>: load a new audio file")
    print("  plot: plot the amplitude of the current sample")
    print("  info: display information about the current sample")
    print("  autocut: cut samples automatically")
    print("  cut: cut a sample at the current position with the current length")
    print("  am: generate an automixed sample")
    print("  amc: configure the auto mixer")
    print("  am N: after a series `amc ...`, render only combination #N (1-based)")
    print("  amchelp: display the auto mixer help")
    print("  aminf: toggle automix self-feed mode")
    print("  q: quit the program")
