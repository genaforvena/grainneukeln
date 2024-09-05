import cutter.sample_cut_tool as sample_cut_tool
import os
import sys
from PySide6.QtWidgets import QApplication
from main_window import MainWindow

def launch_gui():
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        return app.exec()
    except Exception as e:
        print(f"Error launching GUI: {e}")
        return None

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Granular Sampler")
    parser.add_argument("--gui", action="store_true", help="Launch the graphical user interface")
    parser.add_argument("source_path", nargs="?", help="Path to mp3 file to cut or YouTube URL")
    parser.add_argument("destination_path", nargs="?", help="Directory where cut samples will be saved")
    parser.add_argument("commands", nargs="*", help="A list of commands to execute. If provided, the tool will execute them and make automix when done.")
    
    args = parser.parse_args()

    if args.gui:
        result = launch_gui()
        if result is None:
            print("GUI launch failed. Falling back to CLI mode.")
            args.gui = False

    if not args.gui and args.source_path and args.destination_path:
        if not os.path.isdir(args.destination_path):
            print("Destination path doesn't exist")
            sys.exit(1)
        
        args.destination_path = os.path.abspath(args.destination_path)
        
        if args.source_path.startswith("https://www.youtube.com/"):
            print("Downloading audio from YouTube")
            import youtube.downloader as downloader
            args.source_path = downloader.download_video(args.source_path, args.destination_path)
        
        print("Starting cut tool with file: " + args.source_path)
        sample_cut_tool.main(args.source_path, args.destination_path, args.commands)
    elif not args.gui:
        parser.print_help()
        sys.exit(1)
