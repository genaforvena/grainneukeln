import cutter.sample_cut_tool as sct
import argparse

# /Users/ilyamozerov/Downloads/daddy.mp3
# /Users/ilyamozerov/Downloads/devil.mp3
# /Users/ilyamozerov/Downloads/krug.mp3

def cut_samples(file_path):
    tool = sct.MP3SampleCutTool(file_path)
    tool.select_cut_points()

# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Cut samples from an MP3 file")
    parser.add_argument("file", help="MP3 file to cut samples from")

    args = parser.parse_args()
    cut_samples(args.file)

