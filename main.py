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
    parser.add_argument("--record", nargs="?", type=float, const=10.0, default=None,
                        metavar="SECONDS",
                        help="Record SECONDS of live mic audio (default 10) and use it as the "
                             "source — the CLI half of the TUI's RECORD button. The take is "
                             "MEASURED before it is used: a silent or too-short capture is "
                             "reported and refused rather than handed to the grinder, because a "
                             "muted or already-held mic yields a well-formed wav full of zeros.")
    parser.add_argument("--record-device", default=None,
                        help="Capture source for --record (see --list-inputs). Absent = let the "
                             "backend pick.")
    parser.add_argument("--record-backend", default=None,
                        help="Pin the capture backend: pw-record | parecord | ffmpeg | arecord. "
                             "arecord is raw ALSA and EXCLUSIVE — it locks the card away from "
                             "every other client for the duration. Absent = best available.")
    parser.add_argument("--list-inputs", action="store_true",
                        help="List capture backends and sources this node can actually record "
                             "from, plus any process currently holding a capture device, then "
                             "exit. A device held by a raw-ALSA client is absent from the list.")
    parser.add_argument("--pult", nargs="?", type=int, const=8731, default=None, metavar="PORT",
                        help="Serve the LAN pult — a phone-reachable control surface (record, "
                             "grind, listen) on PORT (default 8731). Prints the URL and the "
                             "access token. LAN only; never expose it to the internet.")
    parser.add_argument("--pult-bind", default="0.0.0.0",
                        help="Interface for --pult (default 0.0.0.0 so a phone on the LAN can "
                             "reach it; use 127.0.0.1 to keep it on this host).")
    parser.add_argument("--low-memory", action="store_true",
                        help="Enable aggressive garbage collection for memory-constrained nodes. "
                             "Slower but uses ~30%% less peak RAM on long sources.")
    parser.add_argument("source_path", nargs="?",
                        help="Path to an audio file to cut, a media URL (YouTube, SoundCloud, "
                             "Bandcamp — anything yt_dlp handles; the host is not gated), or "
                             "free-text search (artist + track → loads the official upload; "
                             "search itself is YouTube-only).")
    parser.add_argument("destination_path", nargs="?", help="Directory where cut samples will be saved")
    parser.add_argument("commands", nargs="*", help="A list of commands to execute. If provided, the tool will execute them and make automix when done.")
    parser.add_argument("--pick", type=int, default=None,
                        help="When source_path is a search query, pick result N (1-based) instead of "
                             "the ranker's #1. The list is printed before download so you can re-run "
                             "with the right N without re-searching.")
    parser.add_argument("--uxn-ctrl", nargs="?", const="__default__", default=None,
                        metavar="ROM_PATH",
                        help="Drive a sequence of renders from a Uxn param-sequencer ROM "
                             "(external control layer, issue #13). Bare flag uses the vendored "
                             "uxn_ctrl/paramgen.rom; or pass a path to your own ROM that emits "
                             "'l <ms> w <n>' lines on stdout. Combine with --uxn-ticks. Bypasses "
                             "the positional `commands` list.")
    # default None (not 8) so `--tui` can tell "the operator asked for N ticks" apart from "nobody
    # said" — an always-set 8 would override the restored session's tick count on every launch.
    parser.add_argument("--uxn-ticks", type=int, default=None,
                        help="Number of ticks (renders) to drive from --uxn-ctrl (default 8).")
    parser.add_argument("--uxn-stride", type=int, default=1,
                        help="Step between tick numbers (default 1 = consecutive). The ROM packs "
                             "l/w/s/c into two bits each of one byte, so CONSECUTIVE ticks only "
                             "move `l` — a 12-tick run at stride 1 holds s and c at their first "
                             "table entry throughout and never moves ss at all. A stride co-prime "
                             "with 256 (try 461) carries into the high bits every tick, so all "
                             "four axes advance together.")
    parser.add_argument("--uxn-start", type=int, default=0,
                        help="First tick number (default 0). Two sources run with the same "
                             "ticks/stride get the SAME recipes; give each a start that continues "
                             "the previous run so a multi-source batch is one non-repeating walk.")
    parser.add_argument("--uxn-feedback", action="store_true",
                        help="Closed-loop Uxn control (issue #13 extension): each tick's ROM call "
                             "is fed a feedback byte measured from the current source's rhythm "
                             "density, so the sequencer's channel-band choice reacts to the actual "
                             "audio instead of ticking open-loop. Only meaningful with --uxn-ctrl; "
                             "default off (byte-identical to today's open-loop behaviour).")

    args = parser.parse_args()

    if args.list_inputs:
        from capture import mic
        backends = mic.available_backends()
        print("capture backends (best first):")
        for b in backends:
            print(f"  {b['name']:<10} {b['binary']}  — {b['why']}")
        if not backends:
            print("  (none — install pipewire-utils, pulseaudio-utils, ffmpeg or alsa-utils)")
        print("capture sources:")
        for d in mic.list_devices():
            kind = "playback loopback" if d["monitor"] else "input"
            print(f"  {d['id']}  [{kind}]")
        holders = mic.who_holds_capture()
        if holders:
            # Named, because a device held here is a device MISSING from the list above — and a
            # missing device reads as broken hardware unless the holder is named.
            print("held capture devices (absent from the list above while held):")
            for h in holders:
                print(f"  {h['device']}  pid {h['pid']}: {h['command'][:80]}")
        sys.exit(0 if backends else 1)

    if args.pult is not None:
        from pult.server import serve
        # A pult has no SOURCE — the phone chooses one. So a lone positional is read as the output
        # directory (`main.py --pult out/`), which is the only thing it could sensibly mean, and
        # saves the operator writing an empty source argument to reach the second slot.
        out = os.path.abspath(args.destination_path or args.source_path or "output")
        os.makedirs(out, exist_ok=True)
        serve(out, host=args.pult_bind, port=args.pult)
        sys.exit(0)

    if args.record is not None:
        from capture import mic
        out = os.path.abspath(args.destination_path or "output")
        os.makedirs(out, exist_ok=True)
        print(f"● Recording {args.record:g}s… (ctrl-c to abort)")
        try:
            m = mic.record_clip(args.record, out, device=args.record_device,
                                backend=args.record_backend)
        except mic.CaptureError as e:
            print(f"Record failed: {e}")
            sys.exit(1)
        print(mic.describe(m, m.get("holders")))
        if m["silent"] or m["too_short"]:
            # Refused, not silently accepted: grinding zeros produces a silent render that the
            # operator reads as a grinder bug. The file is kept so they can override by naming it.
            print(f"Refusing to grind it. Kept at {m['path']} — pass that path to use it anyway.")
            sys.exit(1)
        args.source_path = m["path"]
        print(f"Source ← {m['path']}")

    if args.tui:
        # Every flag reaches the TUI (2026-07-24). Previously `--tui` dropped the positional
        # source AND destination on the floor and printed "--seed accepted but not wired", so
        # `python main.py song.mp3 out/ --seed 5 --tui` opened an empty, unseeded session — three
        # arguments parsed and silently discarded.
        from tui.app import run_tui
        out = args.destination_path or "output"
        if args.destination_path and not os.path.isdir(args.destination_path):
            print("Destination path doesn't exist")
            sys.exit(1)
        run_tui(output_dir=os.path.abspath(out), seed=args.seed, low_memory=args.low_memory,
                source=args.source_path, uxn_rom=args.uxn_ctrl, uxn_ticks=args.uxn_ticks,
                uxn_feedback=args.uxn_feedback)
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

        # Free-text that isn't a URL or local path is treated as a YouTube search
        # for "artist + track". The ranker (youtube.search) biases #1 toward the
        # official Topic/VEVO upload — so `gnk "Radiohead - Karma Police" out/ amc`
        # pulls the studio track, not a fan cover. ``--pick N`` overrides.
        import youtube.search as yts
        if yts.is_url(args.source_path):
            from urllib.parse import urlparse
            print(f"Downloading audio from {urlparse(args.source_path).netloc or 'source'}")
            import youtube.downloader as downloader
            args.source_path = downloader.download_video(args.source_path, args.destination_path)
        elif not yts.is_local_path(args.source_path):
            query = args.source_path
            print(f"Searching YouTube for “{query}”…")
            results = yts.search(query)
            if not results:
                print(f"No results for “{query}”.")
                sys.exit(1)
            pick = args.pick - 1 if args.pick and args.pick > 0 else 0
            if pick >= len(results):
                print(f"--pick {args.pick} is out of range (only {len(results)} results).")
                sys.exit(1)
            for i, r in enumerate(results, 1):
                marker = "▶" if i - 1 == pick else " "
                print(f"  {marker} {i}. {r['title']}")
                print(f"       {r['channel']} · {yts._format_duration(r.get('duration'))}")
            chosen = results[pick]
            print(f"Loading #{pick + 1}: {chosen['title']}")
            import youtube.downloader as downloader
            args.source_path = downloader.download_video(chosen["url"], args.destination_path)

        if args.uxn_ctrl is not None:
            from automixer.uxn_stream import run_uxn_sequence, DEFAULT_ROM
            rom = DEFAULT_ROM if args.uxn_ctrl == "__default__" else args.uxn_ctrl
            print("Starting cut tool with file: " + args.source_path)
            cutter = sample_cut_tool.SampleCutter(args.source_path, args.destination_path,
                                                   low_memory=args.low_memory)
            lines = run_uxn_sequence(cutter, args.uxn_ticks or 8, rom_path=rom,
                                     closed_loop=args.uxn_feedback, stride=args.uxn_stride,
                                     start=args.uxn_start)
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
