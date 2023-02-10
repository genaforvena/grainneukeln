import cutter.sample_cut_tool as sct

# /Users/ilyamozerov/Downloads/daddy.mp3
# /Users/ilyamozerov/Downloads/devil.mp3
# /Users/ilyamozerov/Downloads/krug.mp3

def cut_samples():
    tool = sct.MP3SampleCutTool("/Users/ilyamozerov/Downloads/devil.mp3")
    tool.select_cut_points()

# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    cut_samples()
