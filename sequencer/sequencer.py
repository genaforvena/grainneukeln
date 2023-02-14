from pydub import AudioSegment
import pyaudio
import numpy as np
import time


def play_sequence(file_path):
    # Load the MP3 file using pydub
    sound = AudioSegment.from_mp3(file_path)

    # Get the sample rate and number of channels from the audio file
    sample_rate = sound.frame_rate
    channels = sound.channels

    # Convert the audio file to a numpy array
    samples = np.array(sound.get_array_of_samples())

    # Define the tempo and time signature for the sequence
    tempo = 135  # bpm
    time_signature = 4

    # Calculate the number of samples per beat
    samples_per_beat = int(sample_rate * 60 / tempo)

    # Create an array to hold the sequence
    sequence = []

    # Loop over the number of beats in the time signature
    for i in range(time_signature):
        # Extract a beat of audio from the original file
        beat = samples[i * samples_per_beat: (i + 1) * samples_per_beat]

        # Add the beat to the sequence
        sequence.append(beat)

    # Convert the sequence to a numpy array
    sequence = np.concatenate(sequence)

    # Initialize PyAudio
    p = pyaudio.PyAudio()

    # Open a stream for audio output
    stream = p.open(format=pyaudio.paFloat32,
                    channels=channels,
                    rate=sample_rate,
                    output=True)

    # Start the stream and play the sequence
    stream.start_stream()
    stream.write(sequence.tobytes())

    # Wait for the sequence to finish playing
    time.sleep(len(sequence) / sample_rate)

    # Stop the stream
    stream.stop_stream()
    stream.close()

    # Terminate the PyAudio object
    p.terminate()
