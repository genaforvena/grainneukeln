import datetime
import random
from pydub import AudioSegment
import pydub.effects
import os

def generate_mix(samples_directory, track_length):
    print("Generating mix of " + str(track_length) + " seconds")

    # Find all MP3 files in the directory
    mp3_files = [f for f in os.listdir(samples_directory) if f.endswith('.mp3')]

    random_sound_filename = random.choice(mp3_files)
    print("Random sound: " + random_sound_filename)
    # Create a full path to the file
    random_sound_path = os.path.join(samples_directory, random_sound_filename)
    repeated_sound = AudioSegment.from_file(random_sound_path, format='mp3')
    # repeated_sound = pydub.effects.low_pass_filter(shortest_sound, 300)
    print("Finished applying low pass filter")

    repeat_count = int(track_length / repeated_sound.duration_seconds)
    for i in range(repeat_count):
        repeated_sound = repeated_sound.append(repeated_sound)
        print("Repeating sound " + random_sound_filename + " " + str(i) + " times")

    # Trim the repeated sound to match the desired track length
    repeated_sound = repeated_sound[:track_length * 1000]
    print("Repeating sound " + random_sound_filename + " " + str(repeat_count) + " times")

    # Iterate through each MP3 file and add it to the final mix with a random rhythm
    for i, file in enumerate(mp3_files):
        if file == repeated_sound:
            continue

        sound = AudioSegment.from_file(os.path.join(samples_directory, file), format='mp3')
        print("Adding sound " + file + " to the mix")

        # Apply random volume balancing
        volume_adjustment = random.uniform(0.5, 1.5)
        sound = pydub.effects.apply_gain_stereo(volume_adjustment)
        print("Volume adjustment: " + str(volume_adjustment))

        # Apply random equalization
        sound = pydub.effects.invert_phase(sound)
        print("Equalization: inverted phase")

        # Add the sound to the mix with a random rhythm
        sound_start = random.uniform(0, track_length - sound.duration_seconds)
        mix = mix.overlay(sound, position=sound_start * 1000)
        print("Done adding sound " + file + " to the mix")

    # Save the final mix to an MP3 file
    repeated_sound.export("../mixes/mix" + str(datetime.date.today()) + ".mp3", format='mp3')