import cutter.sample_cut_tool as sample_cut_tool


if __name__ == '__main__':
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Path to mp3 file to cut or youtube url")
    args = parser.parse_args()
    if args.path.startswith("https://www.youtube.com/"):
        print("Downloading audio from youtube")
        import youtube.downloader as downloader
        args.path = downloader.download_video(args.path)
    print("Starting cut tool with file: " + args.path)
    sample_cut_tool.main(args.path)

