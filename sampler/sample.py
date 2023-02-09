import pydub
import pydub.effects
import pydub.playback
from pydub import AudioSegment


class Sampler:
    def __init__(self):
        self.tracks = []

    def load_track(self, filename):
        track = pydub.AudioSegment.from_mp3(filename)
        # Convert to mono as otherwise it will not merge tracks
        self.tracks.append(track.set_channels(1))

    def merge_tracks(self):
        print("Merging tracks")
        for track in self.tracks:
            print(track.channels)
        # Merge tracks
        merged = pydub.AudioSegment.empty()
        for track in self.tracks:
            merged += track
        print("Merged tracks")
        return merged

    def transform_track(self, track, effects):
        print("Transforming track")
        for effect in effects:
            if effect == 'loudness':
                track = pydub.effects.low_pass_filter(track, 400)
            elif effect == 'speedup':
                track = pydub.effects.speedup(track, 1.5)
        print("Transformed track")
        return track

    def play(self, merged_track):
        print("Playing merged track")
        pydub.playback.play(merged_track)

sampler = Sampler()
