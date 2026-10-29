#!/bin/sh
# Build the one-file Linux executable: dist/PersonaTrace
set -e
cd "$(dirname "$0")/.."
python3 -m pip install --upgrade pyinstaller -r requirements.txt
python3 -m PyInstaller packaging/personatrace.spec --noconfirm
echo "Built: dist/PersonaTrace"
./dist/PersonaTrace --help
