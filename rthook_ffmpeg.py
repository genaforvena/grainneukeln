# PyInstaller runtime hook: make pydub find the ffmpeg/ffprobe we ship next to the executable.
# The release workflow drops static ffmpeg + ffprobe into the bundle dir; here we point pydub at
# them so a friend never has to install ffmpeg. Falls back to a system ffmpeg (PATH) if none shipped.
import os
import sys

_bundle = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
_ext = ".exe" if sys.platform.startswith("win") else ""

for _name in ("ffmpeg", "ffprobe"):
    _cand = os.path.join(_bundle, _name + _ext)
    if os.path.isfile(_cand):
        os.environ["PATH"] = _bundle + os.pathsep + os.environ.get("PATH", "")
        try:
            from pydub import AudioSegment
            if _name == "ffmpeg":
                AudioSegment.converter = _cand
            else:
                AudioSegment.ffprobe = _cand
        except Exception:
            pass
