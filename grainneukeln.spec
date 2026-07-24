# grainneukeln.spec — PyInstaller build for friend-shippable bundles (Win/Mac/Linux).
# Built per-OS by .github/workflows/release.yml (PyInstaller can't cross-compile).
# One onedir bundle exposing the whole app: `grainneukeln <src> <dst> amc ...` (CLI grind),
# `grainneukeln --tui` (terminal UI), `grainneukeln --gui` (PySide6 desktop UI).
#
# The hard deps are librosa (lazy imports + data), numba, soundfile (bundled libsndfile),
# scipy, and pydub (needs ffmpeg at runtime — see rthook_ffmpeg.py, which points pydub at the
# ffmpeg binary we ship next to the executable).
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# Collect the awkward scientific/audio stack fully — these have data files and/or lazy imports
# that PyInstaller's static analysis misses.
for pkg in ("librosa", "soundfile", "scipy", "numba", "llvmlite", "lazy_loader",
            "sklearn", "audioread", "pooch", "soxr", "yt_dlp"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

# Optional UI stacks: include when installed, skip cleanly when not (a CLI-only build still works).
for pkg in ("PySide6", "pyqtgraph", "matplotlib", "textual", "pyfiglet"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

# The app's own packages are imported dynamically in places (uxn_stream, youtube.*, tui.app).
for pkg in ("automixer", "cutter", "tui", "youtube"):
    hiddenimports += collect_submodules(pkg)

# Ship the vendored Uxn control ROMs (paramgen.rom drives --uxn-ctrl).
datas += [("uxn_ctrl", "uxn_ctrl")]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=["rthook_ffmpeg.py"],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="grainneukeln",
    console=True,          # keep a console: the CLI grind + TUI need stdio; --gui still opens a window
    icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="grainneukeln",
)
