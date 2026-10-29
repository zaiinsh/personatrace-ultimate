#!/bin/sh
# PersonaTrace v9 — one-command trained local NLP setup.
# Installs spaCy + the small English model (en_core_web_sm, ~12 MB).
# PersonaTrace auto-detects it at runtime and uses it for NER,
# labelled with the model name. The model is NOT bundled in the ZIP
# (size); this script is the one-command local install. No cloud,
# no API key.
set -e
python3 -m pip install --upgrade spacy
python3 -m spacy download en_core_web_sm
python3 -c "import spacy; spacy.load('en_core_web_sm'); print('spaCy + en_core_web_sm ready.')"
