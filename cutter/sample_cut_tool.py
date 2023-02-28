import pydub.playback
import pydub.effects
import pydub.utils
from pydub import AudioSegment
import matplotlib.pyplot as plt
import os


class MP3SampleCutTool:
    def __init__(self, audio_file_path):
        self.audio_file_path = audio_file_path
        self.audio = AudioSegment.from_mp3(audio_file_path)
        self.current_position = 0
        self.length = 5000
        self.step = 1000
        self.show_help()

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
            elif command.startswith("q"):
                picking = False
                print("Quitting the cut tool")
            elif command.startswith("cut"):
                self.cut_track(command)

    def play_audio(self):
        pydub.playback.play(self.audio[self.current_position:self.current_position + self.length])

    def set_beginning(self, command):
        if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
            self.current_position = int(command.split(" ")[1]) * 1000

    def set_length(self, command):
        if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
            length = int(command.split(" ")[1]) * 1000
            if length > 15000:
                length = 15000
            if length < 1000:
                length = 1000
            if self.current_position + length > len(self.audio):
                length = len(self.audio) - self.current_position
            self.length = length
            print("Length: " + str(self.length / 1000))

    def set_step(self, command):
        if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
            self.step = int(command.split(" ")[1]) * 1000
            print("Step: " + str(self.step / 1000))

    def fast_forward(self, command):
        if len(command) == command.count("f"):
            self.current_position += self.step * len(command)

    def rewind(self, command):
        if len(command) == command.count("r"):
            self.current_position -= self.step * len(command)

    def show_help(self):
        print("p - play selected to cut part of the track")
        print("b <seconds> - set beginning of the sample")
        print("l <seconds> - set length of the sample")
        print("s <seconds> - set step for forward and rewind")
        print("f - forward. You can use multiple f's to fast forward (e.g. fff - fast forward 3 times)")
        print("r - rewind. You can use multiple r's to rewind (e.g. rrr - rewind 3 times)")
        print("plot - plot amplitude of the selected part of the track")
        print("info - print information about cutting the track")
        print("load <filepath> - change the track to cut")
        print("cut - cut the track")
        print("cut -a - cut the track and adjust the cut position")
        print("q - quit")

    def load_file(self, command):
        audio_file_path = command.split(" ")[1]
        if not os.path.isfile(audio_file_path):
            print("File doesn't exist")
            return
        self.audio_file_path = audio_file_path
        self.audio = AudioSegment.from_mp3(audio_file_path)
        self.select_cut_points()
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
        print("Current position: " + str(self.current_position / 1000))
        print("Length: " + str(self.length))
        print("Step: " + str(self.step))

    def cut_track(self, command):
        adjust_cut_position = " -a" in command
        self._cut_track(self.current_position, self.length, adjust_cut_position)

    def _cut_track(self, start_cut, length, adjust_cut_position=False):
        # Cut the track using the selected cut points
        if adjust_cut_position:
            start_cut = self._adjust_cut_position(start_cut, length)

        end_cut = start_cut + length
        cut_audio = self.audio[start_cut:end_cut]
        original_name = os.path.basename(self.audio_file_path).split(".")[0]
        sample_file_name = original_name + "_" + str(start_cut) + "_" + str(length) + ".wav"
        cut_audio.export("samples/" + sample_file_name, format="wav")
        print("Saved " + sample_file_name)

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


def main(filepath=None):
    if not os.path.isfile(filepath):
        filepath = input("Path to mp3 file to cut\n>>>>")
        # Check if the file exists
        if not os.path.isfile(filepath):
            print("File doesn't exist")
            return
    cut_tool = MP3SampleCutTool(filepath)
    cut_tool.run()
