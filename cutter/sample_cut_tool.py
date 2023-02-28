import random

import pydub.playback
import pydub.effects
import pydub.utils
from pydub import AudioSegment
import matplotlib.pyplot as plt
import os
import madmom


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
        self.current_position = 0
        self.beats = self._detect_beats()
        self.step = self._calculate_step()
        self.length = self.step * 4
        self.show_help()
        self.destination_path = destination_path

    def _detect_beats(self):
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

    def run(self):
        picking = True
        while picking:
            command = input(">>>")
            if command.startswith("p") and command != "plot":
                self.play_audio()
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
            elif command.startswith("automix"):
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
        print("automix - cut the whole track from the beginning to the end with the given step and mix it into one track")
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

    def cut_track(self, command):
        adjust_cut_position = " -a" in command
        self._cut_track(self.current_position, self.length, adjust_cut_position)

    def automix(self, command):
        mix = AudioSegment.empty()
        if len(command.split(" ")) < 2:
            mix = self._random_automix(mix)
        elif command.split(" ")[1] == "3chan":
            mix = self._3chan_automix(mix)
        mix.export(os.path.join(self.destination_path, "mix.wav"), format="wav")
        print("Saved mix.wav to " + self.destination_path)

    def _3chan_automix(self, mix):
        start_cut = 0
        while start_cut + self.length < len(self.audio):
            start_low = random.choice(self.beats)
            start_mid = random.choice(self.beats)
            start_high = random.choice(self.beats)
            if start_low + self.length > len(self.audio) or start_high + self.length > len(self.audio) or start_mid + self.length > len(self.audio):
                continue
            print("Cutting low from " + str(start_low) + " to " + str(start_low + self.length))
            print("Part length: " + str(len(self.audio[start_low:start_low + self.length])))
            print("Cutting mid from " + str(start_mid) + " to " + str(start_mid + self.length))
            print("Part length: " + str(len(self.audio[start_mid:start_mid + self.length])))
            print("Cutting high from " + str(start_high) + " to " + str(start_high + self.length))
            print("Part length: " + str(len(self.audio[start_high:start_high + self.length])))
            mix = mix.append(
                pydub.effects.low_pass_filter(self.audio[start_low: start_low + self.length], 300).overlay(
                    pydub.effects.high_pass_filter(self.audio[start_high: start_high + self.length], 900)
                ).overlay(
                    pydub.effects.low_pass_filter(self.audio[start_mid: start_mid + self.length], 900).overlay(
                        pydub.effects.high_pass_filter(self.audio[start_mid: start_mid + self.length], 300)
                    )
                ), crossfade=0)
            print(len(mix))
            start_cut += self.length
        return mix

    def _random_automix(self, mix):
        start_cut = 0
        while start_cut + self.length < len(self.audio):
            start = random.choice(self.beats)
            if start + self.length > len(self.audio):
                continue
            print("Cutting from " + str(start) + " to " + str(start + self.length))
            print("Part length: " + str(len(self.audio[start:start + self.length])))
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
