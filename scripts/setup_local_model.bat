@echo off
REM One-click local model setup (Windows): requires Ollama from https://ollama.com/download
ollama pull llama3
ollama pull llava
echo Done. Set PERSONATRACE_LOCAL_MODEL_URL=http://localhost:11434
