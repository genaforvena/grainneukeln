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

    def select_cut_points(self):
        # Create a variable to keep track of the current playback position
        current_position = 0

        # Create a variable to keep track of the status of the playback (running or stopped)
        picking = True
        length = 5000 # 5 seconds
        step = 1000 # 1 second

        # Create a loop to continuously check for user commands
        while picking:
            # Get the user command
            command = input("Commands: "
                            "b (time_sec)\n"
                            "p\n"
                            "f\n" 
                            "r\n"
                            "l (time_sec)\n"
                            "s (time_sec)\n"
                            "plot \n"
                            "cut \n"
                            "q \n"
                            "You command:>>>")

            # Start the playback
            if command.startswith("p") and command != "plot":
                # Check if play command has time argument
                if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
                    print("Playing from " + command.split(" ")[1] + " seconds")
                    current_position = int(command.split(" ")[1])

                pydub.playback.play(self.audio[current_position:current_position + length])

            # Set the beginning of the playback
            elif command.startswith("b"):
                # Ensure that the beginning is a number
                if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
                    current_position = int(command.split(" ")[1]) * 1000

            # Set the length of the playback
            elif command.startswith("l"):
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

            # Set the step of the playback
            elif command.startswith("s"):
                # Ensure that the length is a number
                if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
                    step = int(command.split(" ")[1]) * 1000

            # Forward the playback
            elif command.startswith("f"):
                current_position += step

            elif command.startswith("plot"):
                # Extract the samples for the selected part of the track
                selected_samples = self.audio[current_position:current_position+length].get_array_of_samples()

                # Plot the amplitude of each sample as a function of time
                time = [i / self.audio.frame_rate for i in range(len(selected_samples))]
                plt.plot(time, selected_samples)
                plt.xlabel("Time (s)")
                plt.ylabel("Amplitude")
                plt.show()

            # Rewind the playback
            elif command.startswith("r"):
                current_position -= step

            # Quit the cut tool
            elif command.startswith("q"):
                picking = False

            # Cut the track
            elif command.startswith("cut"):
                self.cut_track(current_position, current_position + length, length)

    def cut_track(self, start_cut, end_cut, length):
        # Cut the track using the selected cut points
        cut_audio = self.audio[start_cut:end_cut]
        original_name = os.path.basename(self.audio_file_path)
        sample_file_name = original_name + "_" + str(start_cut) + "_" + str(length) + ".mp3"
        cut_audio.export(sample_file_name, format="mp3")
        print("Saved " + sample_file_name)

