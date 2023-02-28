import cutter.sample_cut_tool as sample_cut_tool


if __name__ == '__main__':
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("filepath", help="Path to mp3 file to cut")
    args = parser.parse_args()
    sample_cut_tool.main(args.filepath)

