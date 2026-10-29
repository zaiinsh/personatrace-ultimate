# PersonaTrace v9 — PyInstaller spec (one-file GUI launcher).
# Build:  pyinstaller packaging/personatrace.spec
# Output: dist/PersonaTrace (single executable; starts the GUI and
# opens the browser). The personatrace package + GUI static files are
# bundled as data so the frozen app serves the real dashboard.
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "run_personatrace.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "personatrace", "gui", "static"), os.path.join("personatrace", "gui", "static")),
        (os.path.join(ROOT, "curated_sherlock.json"), "."),
        (os.path.join(ROOT, "curated_whatsmyname.json"), "."),
    ],
    hiddenimports=[
        "personatrace.cli", "personatrace.gui.server",
        "personatrace.features.v9", "personatrace.features.v8",
        "personatrace.features.v7", "personatrace.features.v6",
        "PIL", "reportlab",
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["pytest", "playwright"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="PersonaTrace",
    debug=False, bootloader_ignore_signals=False, strip=False,
    upx=False, console=True,
)
