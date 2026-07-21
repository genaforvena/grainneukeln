import cutter.sample_cut_tool as sample_cut_tool
import os
import sys

def launch_gui():
    try:
        # GUI deps (PySide6) imported lazily so headless CLI automix runs without them installed.
        from PySide6.QtWidgets import QApplication
        from main_window import MainWindow
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
    parser.add_argument("--tui", action="store_true", help="Launch the terminal UI (headless-friendly)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Seed every mixer's RNG so two runs with the same seed + params are "
                             "byte-identical. Injected into the amc command as `seed <N>`. Absent = "
                             "legacy unseeded behaviour (runs differ as before).")
    parser.add_argument("--low-memory", action="store_true",
                        help="Enable aggressive garbage collection for memory-constrained nodes. "
                             "Slower but uses ~30%% less peak RAM on long sources.")
    parser.add_argument("source_path", nargs="?", help="Path to mp3 file to cut or YouTube URL")
    parser.add_argument("destination_path", nargs="?", help="Directory where cut samples will be saved")
    parser.add_argument("commands", nargs="*", help="A list of commands to execute. If provided, the tool will execute them and make automix when done.")
    parser.add_argument("--uxn-ctrl", nargs="?", const="__default__", default=None,
                        metavar="ROM_PATH",
                        help="Drive a sequence of renders from a Uxn param-sequencer ROM "
                             "(external control layer, issue #13). Bare flag uses the vendored "
                             "uxn_ctrl/paramgen.rom; or pass a path to your own ROM that emits "
                             "'l <ms> w <n>' lines on stdout. Combine with --uxn-ticks. Bypasses "
                             "the positional `commands` list.")
    parser.add_argument("--uxn-ticks", type=int, default=8,
                        help="Number of ticks (renders) to drive from --uxn-ctrl (default 8).")

    args = parser.parse_args()

    if args.tui:
        from tui.app import run_tui
        run_tui(seed=args.seed, low_memory=args.low_memory)
        sys.exit(0)

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

        if args.uxn_ctrl is not None:
            from automixer.uxn_stream import run_uxn_sequence, DEFAULT_ROM
            rom = DEFAULT_ROM if args.uxn_ctrl == "__default__" else args.uxn_ctrl
            print("Starting cut tool with file: " + args.source_path)
            cutter = sample_cut_tool.SampleCutter(args.source_path, args.destination_path,
                                                   low_memory=args.low_memory)
            lines = run_uxn_sequence(cutter, args.uxn_ticks, rom_path=rom)
            for i, line in enumerate(lines):
                print(f"[uxn tick {i}] {line}")
            sys.exit(0)

        # Inject `seed N` right after the leading `amc` token when --seed is passed and the user
        # didn't already write `seed M` in the command. Lets `--seed 5` make any automix reproducible
        # without changing the amc grammar; an explicit `seed M` later in the command still overrides.
        commands = list(args.commands)
        if args.seed is not None and commands and commands[0] == "amc" and "seed" not in commands:
            commands[1:1] = ["seed", str(args.seed)]
        print("Starting cut tool with file: " + args.source_path)
        sample_cut_tool.main(args.source_path, args.destination_path, commands, low_memory=args.low_memory)
    elif not args.gui:
        parser.print_help()
        sys.exit(1)
