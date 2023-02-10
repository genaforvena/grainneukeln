import numpy as np
import pandas as pd
import pydub.playback
import pydub.effects
import pydub.utils
from pydub import AudioSegment


class MP3SampleCutTool:
    def __init__(self, audio_file_path):
        self.audio_file_path = audio_file_path
        self.audio = AudioSegment.from_mp3(audio_file_path)
        self.start_cut = None
        self.end_cut = None

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
            command = input("Enter a command (play, stop, forward, rewind, quit, length, step, cut): ")

            # Start the playback
            if command.startswith("play"):
                # Check if play command has time argument
                if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
                    current_position = int(command.split(" ")[1])

                pydub.playback.play(self.audio[current_position:current_position + length])

            # Set the length of the playback
            elif command.startswith("length"):
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
            elif command.startswith("step"):
                # Ensure that the length is a number
                if len(command.split(" ")) > 1 and command.split(" ")[1].isdigit():
                    step = int(command.split(" ")[1]) * 1000

            # Stop the playback
            elif command.startswith("stop"):
                running = False

            # Forward the playback
            elif command.startswith("forward"):
                current_position += step

            # Rewind the playback
            elif command.startswith("rewind"):
                current_position -= step

            # Cut the track
            elif command.startswith("cut"):
                if self.start_cut is None:
                    self.start_cut = current_position
                    print("Start cut point set to", current_position)
                elif self.end_cut is None:
                    self.end_cut = current_position + length
                    print("End cut point set to", current_position)
                    picking = False
                    self.cut_track()

            # Quit the loop
            elif command.startswith("quit"):
                break

    def cut_track(self, start_cut, end_cut):
        input("Press enter to start cutting the track")
        # Cut the track using the selected cut points
        cut_audio = self.audio[self.start_cut:self.end_cut]
        filename = os.path.basename(self.audio_file_path)
        cut_audio.export(filename+self.start_cut+self.end_cut+".mp3", format="mp3")

