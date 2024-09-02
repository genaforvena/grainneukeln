import sys
import os
import traceback
import argparse
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QToolTip

from cutter.sample_cut_tool import SampleCutter
from automixer.config import AutoMixerConfig
from automixer.runner import AutoMixerRunner
from youtube.downloader import download_video
from ui import MainWindow

def main():
    parser = argparse.ArgumentParser(description="Sample Cutter and AutoMixer GUI")
    parser.add_argument("--source", help="Path to mp3 file to cut or YouTube URL")
    parser.add_argument("--destination", help="Directory where cut samples will be saved", default="samples")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    
    # Set global tooltip style
    QToolTip.setFont(QFont('SansSerif', 10))
    
    window = MainWindow()
    
    if args.source:
        if args.source.startswith("https://www.youtube.com/"):
            window.output_text.append("Downloading audio from YouTube")
            file_path = download_video(args.source, args.destination)
        else:
            file_path = args.source
        
        window.audio_file_path = file_path
        window.file_label.setText(f"Selected file: {file_path}")
        window.output_text.append(f"Loaded file: {file_path}")
        window.select_file()  # This will trigger beat detection

    window.show()
    
    try:
        exit_code = app.exec()
        app.deleteLater()
        sys.exit(exit_code)
    except Exception as e:
        print(f"An error occurred: {e}")
        print("Traceback:")
        traceback.print_exc()
    finally:
        try:
            app.quit()
        except:
            pass

if __name__ == "__main__":
    main()
