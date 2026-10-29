#!/usr/bin/env python3
"""PersonaTrace one-click launcher.

Double-click (or run) this file: it starts the PersonaTrace GUI on a
local port and opens it in your default browser. No terminal needed.

    python run_personatrace.py            # GUI in the browser
    python run_personatrace.py --cli ...  # pass through to the CLI
    python run_personatrace.py --help     # this text
"""
import os
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--cli":
        from personatrace.cli import main as cli_main
        return cli_main(argv[1:])
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    port = 8790
    if argv and argv[0].isdigit():
        port = int(argv[0])
    import time
    from personatrace.gui.server import run_gui
    server = run_gui(port=port)  # serves on its own daemon thread
    url = f"http://127.0.0.1:{port}/"
    print(f"PersonaTrace GUI running at {url} — opening your browser. Close this window to stop.")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
