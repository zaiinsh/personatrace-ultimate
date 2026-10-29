# Install PersonaTrace v9

## End users — 3 steps (no Python, no terminal)

1. **Download** the PersonaTrace ZIP for your system and unzip it.
2. **Double-click** `PersonaTrace` (Linux/macOS) or `PersonaTrace.exe` (Windows).
3. Your browser opens the dashboard at `http://127.0.0.1:8790/`. Done —
   type a username and press **Search live**.

> If no prebuilt executable was included with your copy, use the
> Python route below, or ask whoever gave you the ZIP to run the
> builder steps once.

## Python route (any OS)

1. Install Python 3.12+.
2. Unzip, open a terminal in the `personatrace-app` folder.
3. `pip install -r requirements.txt` then double-click
   `run_personatrace.py` (or run `python run_personatrace.py`).

Optional extras, one command each, still no keys:
- Browser screenshots: `pip install playwright && playwright install firefox`
- Local transcription: `scripts/setup_whisper.sh`
- Trained local NLP: `scripts/setup_local_nlp.sh`

## Builders — produce the one-click executable

- Linux: `packaging/build_installer.sh`
- Windows: `packaging\build_installer.bat`
- macOS: `packaging/build_installer_macos.sh`

Each installs PyInstaller, builds from `packaging/personatrace.spec`,
and smoke-runs the result with `--help`. Output: `dist/PersonaTrace`
(or `dist\PersonaTrace.exe`). Ship that single file together with
this guide; end users then follow the 3 steps above.
