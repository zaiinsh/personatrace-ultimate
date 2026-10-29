@echo off
REM Build the one-file Windows executable: dist\PersonaTrace.exe
cd /d %~dp0\..
python -m pip install --upgrade pyinstaller -r requirements.txt
python -m PyInstaller packaging\personatrace.spec --noconfirm
echo Built: dist\PersonaTrace.exe
dist\PersonaTrace.exe --help
