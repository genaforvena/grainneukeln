import random
import time

import pydub.playback
import pydub.effects
import pydub.utils
from pydub import AudioSegment
import pyrubberband as pyrb
import numpy as np
import matplotlib.pyplot as plt
import os
import madmom
from tqdm import tqdm
from datetime import datetime


class SampleCutter:
    def __init__(self, audio_file_path, destination_path):
        self.audio_file_path = audio_file_path
        # Check if file exists is wav or mp3 or webm or m4a
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
            raise Exception("File is not wav or mp3")
        print("Loaded file: " + audio_file_path)
        self.current_position = 0
        self.beats = self._detect_beats()
        self.step = self._calculate_step()
        self.length = self.step * 4
        self.show_help()
        self.destination_path = destination_path
        self.isWavExportEnabled = False
        self.isVerboseModeEnabled = False
        try:
            import readline
            # Set the completer function
            readline.set_completer(self.__completer)
            # Enable tab completion
            readline.parse_and_bind('tab: complete')
        except ImportError:
            print("Readline not available. You're probably using Windows.")
        print("Ready to cut samples")

    def _detect_beats(self):
        print("Detecting beats...")
        import numpy as np
        beat_probabilities = madmom.features.beats.RNNBeatProcessor()(self.audio_file_path)
        beat_positions = madmom.features.beats.DBNBeatTrackingProcessor(fps=100)(beat_probabilities)
        beat_positions = np.vectorize(lambda x: int(x * 1000))(beat_positions)
        return beat_positions

    def _calculate_step(self):
        # Calculate the step size as the average distance between the beats
        step = 0
        for i in range(1, len(self.beats)):
            step += self.beats[i] - self.beats[i - 1]
        step /= len(self.beats) - 1
        return step

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
            if command.startswith("p") and command != "plot":
                self.play_audio()
            elif command.startswith("set_wav_enabled"):
                self.isWavExportEnabled = True
                print("Wav export enabled")
            elif command.startswith("set_wav_disabled"):
                self.isWavExportEnabled = False
                print("Wav export disabled")
            elif command.startswith("set_verbose_enabled"):
                self.isVerboseModeEnabled = True
                print("Verbose enabled")
            elif command.startswith("set_verbose_disabled"):
                self.isVerboseModeEnabled = False
                print("Verbose disabled")
            elif command.startswith("b"):
                self.set_beginning(command)
            elif command.startswith("l"):
                self.set_length(command)
            elif command.startswith("s"):
                self.set_step(command)
            elif command.startswith("f"):
                self.fast_forward(command)
            elif command.startswith("r"):
                self.rewind(command)
            elif command.startswith("help"):
                self.show_help()
            elif command.startswith("load"):
                self.load_file(command)
            elif command.startswith("plot"):
                self.plot_amplitude()
            elif command.startswith("info"):
                self.show_info()
            elif command.startswith("autocut"):
                self.autocut(command)
            elif command.startswith("automix") or command.startswith("am"):
                self.automix(command)
            elif command.startswith("q"):
                picking = False
                print("Quitting the cut tool")
            elif command.startswith("cut"):
                self.cut_track(command)

    def play_audio(self):
        pydub.playback.play(self.audio[self.current_position:self.current_position + self.length])

    def set_beginning(self, command):
        if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
            self.current_position = int(command.split(" ")[1])

    def set_length(self, command):
        if "*" in command:
            self.length = int(command.split("*")[1]) * self.length
        if "/" in command:
            self.length = self.length / int(command.split("/")[1])

        if len(command.split(" ")) == 2:
            arg = command.split(" ")[1]
            if arg.isdigit():
                self.length = float(arg)
        print("Length: " + str(self.length))

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

    def show_help(self):
        print("p - play selected to cut part of the track")
        print("b <ms> - set beginning of the sample")
        print("l <ms> - set length of the sample")
        print("s <ms> - set step for forward and rewind")
        print("f - forward. You can use multiple f's to fast forward (e.g. fff - fast forward 3 times)")
        print("r - rewind. You can use multiple r's to rewind (e.g. rrr - rewind 3 times)")
        print("plot - plot amplitude of the selected part of the track")
        print("info - print information about cutting the track")
        print("load <filepath> - change the track to cut")
        print("cut - cut the track")
        print("cut -a - cut the track and adjust the cut position")
        print("autocut [number of samples] - cut the whole track from the beginning to the end with the given step, number of samples is optional parameter how many samples will be cut")
        print("am <mode> <playback_speed> - cut the whole track from the beginning to the end with the given step and mix it into one track")
        print("set_wav_enabled - enable wav export")
        print("set_wav_disabled - disable wav export")
        print("set_verbose_enabled - enable verbose mode")
        print("set_verbose_disabled - disable verbose mode")
        print("q - quit")

    def load_file(self, command):
        audio_file_path = command.split(" ")[1]
        if not os.path.isfile(audio_file_path):
            print("File doesn't exist")
            return
        self.audio_file_path = audio_file_path
        self.audio = AudioSegment.from_mp3(audio_file_path)
        self.beats = self._detect_beats()
        print("File loaded from " + audio_file_path)

    def plot_amplitude(self):
        selected_samples = self.audio[self.current_position:self.current_position + self.length].get_array_of_samples()
        time = [i / self.audio.frame_rate for i in range(len(selected_samples))]
        plt.plot(time, selected_samples)
        plt.xlabel("Time (s)")
        plt.ylabel("Amplitude")
        plt.show()

    def show_info(self):
        print("File path: " + self.audio_file_path)
        print("Current position: " + str(self.current_position) + " ms")
        print("Length: " + str(self.length))
        print("Step: " + str(self.step))
        print("Wav export enabled: " + str(self.isWavExportEnabled))
        print("Verbose mode enabled: " + str(self.isVerboseModeEnabled))

    def cut_track(self, command):
        adjust_cut_position = " -a" in command
        self._cut_track(self.current_position, self.length, adjust_cut_position)

    def automix(self, command):
        mix = AudioSegment.empty()
        if len(command.split(" ")) < 2:
            mix = self._random_automix(mix)
        elif command.split(" ")[1] == "3":
            mix = self._3chan_automix(mix)
        elif command.split(" ")[1] == "3w":
            speed = 1.0
            if len(command.split(" ")) == 3:
                speed = float(command.split(" ")[2])
            mix = self._3chan_window_automix(mix, speed)

        # Extract file name from path
        original_file_name = self.audio_file_path.split("/")[-1].split(".")[0]
        now = datetime.now()
        timestamp = now.strftime("%Y_%m_%d_%H%M")

        file_name = original_file_name + "___mix_cut" + str(int(self.length)) + f"-vtgsmlpr____{timestamp}"
        if self.isWavExportEnabled:
            mix.export(os.path.join(self.destination_path, file_name + ".wav"), format="wav")
            print("Saved " + file_name + ".wav to " + self.destination_path)
        mix.export(os.path.join(self.destination_path, file_name + ".mp3"), format="mp3")
        print("Saved " + file_name + ".mp3 to " + self.destination_path)

    def _3chan_automix(self, mix):
        start_cut = 0
        index = 0
        tries = 0
        pbar = tqdm(total=len(self.beats))
        while start_cut + self.length < len(self.audio) and index < len(self.beats):
            start_low = random.choice(self.beats)
            start_mid = random.choice(self.beats)
            start_high = random.choice(self.beats[index:])
            if tries > 100:
                return mix
            if start_low + self.length == len(self.audio) or start_high + self.length == len(self.audio) or start_mid + self.length == len(self.audio):
                return mix
            if start_low + self.length > len(self.audio) or start_high + self.length > len(self.audio) or start_mid + self.length > len(self.audio):
                tries += 1
                continue
            if self.isVerboseModeEnabled:
                print("Cutting low from " + str(start_low) + " to " + str(start_low + self.length))
                print("Cutting mid from " + str(start_mid) + " to " + str(start_mid + self.length))
                print("Cutting high from " + str(start_high) + " to " + str(start_high + self.length))
            mix = mix.append(
                pydub.effects.low_pass_filter(self.audio[start_low: start_low + self.length], 300).overlay(
                    pydub.effects.high_pass_filter(self.audio[start_high: start_high + self.length], 900)
                ).overlay(
                    pydub.effects.low_pass_filter(self.audio[start_mid: start_mid + self.length], 900).overlay(
                        pydub.effects.high_pass_filter(self.audio[start_mid: start_mid + self.length], 300)
                    )
                ), crossfade=0)
            if self.isVerboseModeEnabled:
                print("Mix length: " + str(len(mix)))
            start_cut += self.length
            pbar.update(index)
            index += 1
        pbar.close()
        return mix

    def _3chan_window_automix(self, mix, speed):
        print("Speed: " + str(speed))
        start_cut = 0
        index = 0
        window_size = len(self.beats) / 6
        tries = 0
        pbar = tqdm(total=len(self.beats))
        while start_cut < len(self.audio):
            start = int(index)
            end = int(index * window_size)

            if start >= len(self.beats):
                print("Reached the end of track. Cut start: " + str(start) + " End: " + str(len(self.beats)))
                break

            if end >= len(self.beats):
                end = len(self.beats) - 1

            if start == end:
                start = 0
                end = len(self.beats) - 1

            start_low = random.choice(self.beats[start:end])
            start_mid = random.choice(self.beats[start:end])
            start_high = random.choice(self.beats[start:end])
            if tries > 100000:
                print("Tries exceeded")
                break
            if start_low + self.length >= len(self.audio) or start_high + self.length >= len(
                    self.audio) or start_mid + self.length >= len(self.audio):
                print("Start or end out of range. Start: " + str(start) + " End: " + str(end))
                tries += 1
                continue
            if self.isVerboseModeEnabled:
                print("Cutting low from " + str(start_low) + " to " + str(start_low + self.length))
                print("Cutting mid from " + str(start_mid) + " to " + str(start_mid + self.length))
                print("Cutting high from " + str(start_high) + " to " + str(start_high + self.length))
            highs = pydub.effects.high_pass_filter(self.audio[start_high: start_high + self.length], 300)
            lows_for_mids = pydub.effects.high_pass_filter(self.audio[start_mid: start_mid + self.length], 300)
            mids = pydub.effects.low_pass_filter(lows_for_mids, 900)
            lows = pydub.effects.low_pass_filter(self.audio[start_low: start_low + self.length], 300)

            mix = mix.append(highs.overlay(mids).overlay(lows), crossfade=0)
            if self.isVerboseModeEnabled:
                print("Mix length: " + str(len(mix)))
            start_cut += self.length
            pbar.update(index)
            index += 1
        print("Mix length: " + str(len(mix)) + " Speed: " + str(speed))
        pbar.close()
        if speed != 1.0:
            mix = self._change_audioseg_tempo(mix, speed)
        return mix

    def _change_audioseg_tempo(self, audiosegment, speed):
        print("Changing playback speed to " + str(speed))
        print("Audio length: " + str(len(audiosegment)))
        y = np.array(audiosegment.get_array_of_samples())
        if audiosegment.channels == 2:
            y = y.reshape((-1, 2))

        sample_rate = audiosegment.frame_rate

        y_fast = pyrb.time_stretch(y, sample_rate, speed)

        channels = 2 if (y_fast.ndim == 2 and y_fast.shape[1] == 2) else 1
        y = np.int16(y_fast * 2 ** 15)

        new_seg = pydub.AudioSegment(y.tobytes(), frame_rate=sample_rate, sample_width=2, channels=channels)

        print("New audio length: " + str(len(new_seg)))
        return new_seg

    def _random_automix(self, mix):
        start_cut = 0
        while start_cut + self.length < len(self.audio):
            start = random.choice(self.beats)
            if start + self.length > len(self.audio):
                continue
            if self.isVerboseModeEnabled:
                print("Cutting from " + str(start) + " to " + str(start + self.length))
            mix = mix.append(self.audio[start: start + self.length], crossfade=0)
            print(len(mix))
            start_cut += self.length
        return mix

    def autocut(self, command):
        if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
            samples_to_cut = int(command.split(" ")[1])
            for i in range(samples_to_cut):
                start = random.choice(self.beats)
                if start + self.step > len(self.audio):
                    continue
                self._cut_track(start, self.length)
        else:
            start_cut = 0
            while start_cut + self.length < len(self.audio):
                self._cut_track(start_cut, self.length)
                start_cut += self.step

    def _cut_track(self, start_cut, length, adjust_cut_position=False):
        # Cut the track using the selected cut points
        if adjust_cut_position:
            start_cut = self._adjust_cut_position(start_cut, length)

        end_cut = start_cut + length
        cut_audio = self.audio[start_cut:end_cut]
        original_name = os.path.basename(self.audio_file_path).split(".")[0]
        sample_file_name = original_name + "_" + str(start_cut) + "_" + str(length) + ".wav"
        cut_audio.export(os.path.join(self.destination_path, sample_file_name), format="wav")
        print("Saved " + sample_file_name + " to " + self.destination_path)

    def _adjust_cut_position(self, current_position, length, threshold=0.05):
        # Extract the samples for the selected part of the track
        selected_samples = self.audio[current_position:current_position + length].get_array_of_samples()

        # Calculate the volume levels for the extracted samples
        volume_levels = [abs(sample) for sample in selected_samples]

        # Normalize the volume levels to be in the range of 0-100
        normalized_volume_levels = [level / (2 ** 15) * 100 for level in volume_levels]

        # Find the local maxima of the volume levels
        maxima = []
        for i in range(1, len(normalized_volume_levels) - 1):
            if normalized_volume_levels[i] > normalized_volume_levels[i - 1] and \
                    normalized_volume_levels[i] > normalized_volume_levels[i + 1]:
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
            print("Adjusted cut position from " + str(current_position) + " to " + str(adjusted_position))
            return adjusted_position
        else:
            print("Cut position not adjusted")
            return current_position


def main(filepath=None, destination="samples"):
    if not os.path.isfile(filepath):
        filepath = input("Path to mp3 file to cut\n>>>>")
        # Check if the file exists
        if not os.path.isfile(filepath):
            print("File doesn't exist")
            return
    cut_tool = SampleCutter(filepath, destination)
    cut_tool.run()
