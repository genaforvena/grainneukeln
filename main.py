import sampler
import sampler.sample as s

# /Users/ilyamozerov/Downloads/daddy.mp3
# /Users/ilyamozerov/Downloads/devil.mp3
# /Users/ilyamozerov/Downloads/krug.mp3
def main():
    filenames = [
        "/Users/ilyamozerov/Downloads/duewest.mp3",
        "/Users/ilyamozerov/Downloads/devil.mp3",
        "/Users/ilyamozerov/Downloads/krug.mp3"
    ]

    for filename in filenames:
        s.sampler.load_track(filename)

    effects = ["loudness", "speedup"]
    merged_track = s.sampler.merge_tracks()
    transformed_track = s.sampler.transform_track(merged_track, effects)
    s.sampler.play(transformed_track)


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    main()
