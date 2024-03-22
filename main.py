import cutter.sample_cut_tool as sample_cut_tool
import os


if __name__ == "__main__":
    # Parse command line arguments
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("source_path", help="Path to mp3 file to cut or youtube url")
    parser.add_argument(
        "destination_path", help="Directory where cut samples will be saved"
    )
    parser.add_argument(
        "commands",
        help="A list of commands to execute. If provided the tool will execute them and make automix when done.",
        nargs="*",
        type=str,
    )
    args = parser.parse_args()
    # Check if destination path exists
    if not os.path.isdir(args.destination_path):
        print("Destination path doesn't exist")
        exit()
    args.destination_path = os.path.abspath(args.destination_path)
    if args.source_path.startswith("https://www.youtube.com/"):
        print("Downloading audio from youtube")
        import youtube.downloader as downloader

        args.source_path = downloader.download_video(
            args.source_path, args.destination_path
        )
    print("Starting cut tool with file: " + args.source_path)
    sample_cut_tool.main(args.source_path, args.destination_path, args.commands)
