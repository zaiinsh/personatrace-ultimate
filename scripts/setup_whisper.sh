#!/bin/sh
# PersonaTrace v9 — one-command local transcription setup.
# Installs faster-whisper; the tiny model (~75 MB) downloads once,
# on first transcription use, from Hugging Face. After that,
# transcription runs fully offline. No API key is involved.
set -e
python3 -m pip install --upgrade faster-whisper
python3 - << 'EOF'
from faster_whisper import WhisperModel
print("Downloading the tiny model (one-time)…")
WhisperModel("tiny")
print("Whisper ready: faster-whisper + tiny model cached locally.")
EOF
