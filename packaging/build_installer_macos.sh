#!/bin/sh
# Build the one-file macOS executable: dist/PersonaTrace
# (For a signed .app bundle, wrap dist/PersonaTrace with your own
# bundle/signing step — signing needs your Apple developer identity,
# which is deliberately not part of this build.)
set -e
cd "$(dirname "$0")/.."
python3 -m pip install --upgrade pyinstaller -r requirements.txt
python3 -m PyInstaller packaging/personatrace.spec --noconfirm
echo "Built: dist/PersonaTrace"
./dist/PersonaTrace --help
