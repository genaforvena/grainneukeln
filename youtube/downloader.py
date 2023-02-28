import pytube
import os

# Enter the YouTube video URL
url = "https://www.youtube.com/watch?v=k_bkjsjElrI"

def download_video(url, output_path):
    # Create a YouTube object
    youtube = pytube.YouTube(url)

    # Get the audio stream of the video
    audio_stream = youtube.streams.filter(only_audio=True).first()

    audio_file_name = youtube.title + ".m4a"
    # Download the audio
    audio_stream.download(output_path=os.path.join(output_path, "downloads"), filename=audio_file_name)

    print("Audio downloaded successfully!")

    return os.path.join(output_path, "downloads", audio_file_name)
