#!/bin/bash
# One-click local model setup: installs Ollama if missing, then pulls
# a chat model (llama3) and a vision model (llava) for local use.
# No cloud key is needed after this. Run: bash scripts/setup_local_model.sh
set -e
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama not found. Install it from https://ollama.com/download then re-run this script."
  exit 1
fi
ollama pull llama3
ollama pull llava
echo "Done. Set PERSONATRACE_LOCAL_MODEL_URL=http://localhost:11434 and PERSONATRACE_LOCAL_MODEL_NAME=llama3"
echo "For vision, use a llava model in the GUI Settings > Local model."
