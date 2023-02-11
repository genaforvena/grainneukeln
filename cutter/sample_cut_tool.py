import pydub.playback
import pydub.effects
import pydub.utils
import mixer.mixer
from pydub import AudioSegment
import matplotlib.pyplot as plt
import os


class MP3SampleCutTool:
    def __init__(self, audio_file_path):
        self.audio_file_path = audio_file_path
        self.audio = AudioSegment.from_mp3(audio_file_path)

    def select_cut_points(self):
        # Create a variable to keep track of the current playback position
        current_position = 0

        # Create a variable to keep track of the status of the playback (running or stopped)
        picking = True
        length = 5000 # 5 seconds
        step = 1000 # 1 second

        # Create a loop to continuously check for user commands
        while picking:
            # Make sure that the current position in not out of bounds
            if current_position < 0:
                current_position = 0
            if current_position > len(self.audio):
                current_position = len(self.audio) - length
            print("Current position: " + str(current_position / 1000))
            # Get the user command
            command = input(">>>")

            # Start the playback
            if command.startswith("p") and command != "plot":
                pydub.playback.play(self.audio[current_position:current_position + length])

            # Set the beginning of the playback
            elif command.startswith("b"):
                # Ensure that the beginning is a number
                if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
                    current_position = int(command.split(" ")[1]) * 1000

            # Set the length of the playback
            elif command.split(" ")[0] == "l":
                # Ensure that the length is a number
                if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
                    length = int(command.split(" ")[1]) * 1000
                    # If the length is longer than 15 seconds, set it to 15 seconds
                    if length > 15000:
                        length = 15000
                    # If the length is shorter than 1 second, set it to 1 second
                    if length < 1000:
                        length = 1000
                    # If the current position + length is longer than the audio, set the length to the end of the audio
                    if current_position + length > len(self.audio):
                        length = len(self.audio) - current_position
                print("Length: " + str(length / 1000))

            # Set the step of the playback
            elif command.startswith("s"):
                # Ensure that the length is a number
                if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
                    step = int(command.split(" ")[1]) * 1000
                print("Step: " + str(step / 1000))

            # Forward the playback
            elif command.startswith("f"):
                # If every letter in command is "f", count the number of "f"s
                if len(command) == command.count("f"):
                    current_position += step * len(command)

            # Rewind the playback
            elif command.startswith("r"):
                # If every letter in command is "r", count the number of "r"s
                if len(command) == command.count("r"):
                    current_position -= step * len(command)

            elif command.startswith("help"):
                print("p - play selected to cut part of the track")
                print("b (seconds) - set beginning of the sample")
                print("l (seconds) - set length of the sample")
                print("s (seconds) - set step for forward and rewind")
                print("f - forward. You can use multiple f's to fast forward (e.g. fff - fast forward 3 times)")
                print("r - rewind. You can use multiple r's to rewind (e.g. rrr - rewind 3 times)")
                print("plot - plot amplitude of the selected part of the track")
                print("info - print information about cutting the track")
                print("load (filepath) - change the track to cut")
                print("cut - cut the track")
                print("cut -a - cut the track and adjust the cut position")
                print("mix <seconds>- mix the track from cut samples with the given length")
                print("q - quit")

            elif command.startswith("mix"):
                # Check if the length is given
                if len(command.split(" ")) > 1:
                    # Ensure that the length is a number
                    if command.split(" ")[1].isdigit():
                        length = int(command.split(" ")[1]) * 1000
                # If length is not given, set it to 60 seconds
                else:
                    length = 60000

                mixer.mixer.generate_mix("samples/", length)

            elif command.startswith("load"):
                # Get file path
                audio_file_path = command.split(" ")[1]
                # Check if the file exists
                if not os.path.isfile(audio_file_path):
                    print("File doesn't exist")
                    continue
                # Update the audio file path
                self.audio_file_path = audio_file_path
                # Load the audio file
                self.audio = AudioSegment.from_mp3(audio_file_path)
                self.select_cut_points()
                print("File loaded from " + audio_file_path)

            elif command.startswith("plot"):
                # Extract the samples for the selected part of the track
                selected_samples = self.audio[current_position:current_position+length].get_array_of_samples()

                # Plot the amplitude of each sample as a function of time
                time = [i / self.audio.frame_rate for i in range(len(selected_samples))]
                plt.plot(time, selected_samples)
                plt.xlabel("Time (s)")
                plt.ylabel("Amplitude")
                plt.show()

            # Print the information about the audio file
            elif command.startswith("info"):
                print("File path: " + self.audio_file_path)
                print("Current position: " + str(current_position / 1000))
                print("Length: " + str(length))
                print("Step: " + str(step))

            # Quit the cut tool
            elif command.startswith("q"):
                picking = False

            # Cut the track
            elif command.startswith("cut"):
                if " -a" in command:
                    self._cut_track(current_position, length, adjust_cut_position=True)
                else:
                    self._cut_track(current_position, length, adjust_cut_position=False)

    def _cut_track(self, start_cut, length, adjust_cut_position=False):
        # Cut the track using the selected cut points
        if adjust_cut_position:
            start_cut = self._adjust_cut_position(start_cut, length)

        end_cut = start_cut + length
        cut_audio = self.audio[start_cut:end_cut]
        original_name = os.path.basename(self.audio_file_path).split(".")[0]
        sample_file_name = original_name + "_" + str(start_cut) + "_" + str(length) + ".mp3"
        cut_audio.export("samples/" + sample_file_name, format="mp3")
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

