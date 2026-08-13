# JARVIS V1 — Portability Guide

JARVIS V1 is built to run on Replit today and on a local PC or Raspberry Pi later.
No Replit-specific paths or assumptions are baked into the agent core.

---

## Current deployment: Replit

| Component | How it runs |
|---|---|
| Python agent (`jarvis/`) | `python3 -m jarvis` via the API server workflow |
| API server | Node.js / Express — `artifacts/api-server/` |
| Web interface | Vite + React — `artifacts/jarvis-interface/` |
| Persistent memory | `data/memory.json` (JSON file, workspace-relative) |
| LLM provider | Remote API via `JARVIS_LLM_API_KEY` environment secret |

### Environment variables (Replit)

```
# Core
JARVIS_NAME=JARVIS
JARVIS_VERSION=v1.0.0
JARVIS_DATA_DIR=data

# LLM (remote cloud provider)
JARVIS_LLM_ENABLED=true
JARVIS_LLM_PROVIDER=openai          # openai | anthropic | groq | openrouter
JARVIS_LLM_MODEL=gpt-4o-mini
JARVIS_LLM_API_KEY=<Replit secret>

# Demo (no real AI, scripted responses)
JARVIS_DEMO_MODE=true

# Web research
JARVIS_WEB_RESEARCH_ENABLED=true
```

---

## Local PC (Windows / Linux / macOS)

### Requirements

- Python 3.11+
- Node.js 20+ and pnpm 8+
- (Optional) Ollama or llama.cpp for local LLM

### Steps

```bash
# 1 — Clone the project
git clone <repo-url>
cd jarvis

# 2 — Install Python deps (standard library only — no pip install needed)
#     JARVIS uses no external Python packages.

# 3 — Install Node deps
pnpm install

# 4 — Set environment variables
export JARVIS_DATA_DIR=/home/<user>/.jarvis/data
export JARVIS_LLM_ENABLED=true
export JARVIS_LLM_PROVIDER=openai
export JARVIS_LLM_MODEL=gpt-4o-mini
export JARVIS_LLM_API_KEY=sk-...
export JARVIS_WEB_RESEARCH_ENABLED=true

# 5 — Start the API server
cd artifacts/api-server && pnpm dev

# 6 — Start the web interface (separate terminal)
cd artifacts/jarvis-interface && pnpm dev
```

### Replacing the remote LLM with Ollama (local model)

```bash
# Install Ollama: https://ollama.com
ollama pull llama3

export JARVIS_LLM_ENABLED=false
export JARVIS_LOCAL_PROVIDER_ENABLED=true
export JARVIS_LOCAL_PROVIDER_MODE=http
export JARVIS_LOCAL_ENDPOINT=http://localhost:11434
export JARVIS_LOCAL_MODEL_NAME=llama3
```

No changes to the JARVIS agent code are needed — the `LocalAIProvider` is already
wired in and the Brain interface is identical to `RemoteLLMBrain`.

### Configuration boundaries (PC)

| Capability | Env var | Default |
|---|---|---|
| LLM provider | `JARVIS_LLM_PROVIDER` | `openai` |
| LLM model | `JARVIS_LLM_MODEL` | `gpt-4o-mini` |
| Local endpoint | `JARVIS_LOCAL_ENDPOINT` | `http://localhost:11434` |
| Data directory | `JARVIS_DATA_DIR` | `data` (relative to cwd) |
| Memory file | `JARVIS_MEMORY_FILE` | `$DATA_DIR/memory.json` |
| Web research | `JARVIS_WEB_RESEARCH_ENABLED` | `false` |
| Network probe timeout | `JARVIS_NETWORK_PROBE_TIMEOUT` | `3.0` |
| Sandbox timeout | `JARVIS_SANDBOX_TIMEOUT` | `5.0` |

---

## Raspberry Pi

### Requirements

- Raspberry Pi 4 (4 GB RAM minimum recommended)
- Raspberry Pi OS 64-bit (Bookworm)
- Python 3.11+ (`sudo apt install python3.11`)
- Node.js 20+ (`curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -; sudo apt install nodejs`)
- pnpm (`npm i -g pnpm`)
- (Optional) llama.cpp for on-device inference

### Steps

Follow the PC steps above.  For on-device LLM:

```bash
# Build llama.cpp
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp && make -j4

# Download a small quantised model (fits 4 GB RAM)
wget https://huggingface.co/TheBloke/Llama-3-8B-GGUF/resolve/main/llama-3-8b.Q4_K_M.gguf

# Start the server
./llama-server -m llama-3-8b.Q4_K_M.gguf --port 8080

# Configure JARVIS
export JARVIS_LOCAL_PROVIDER_ENABLED=true
export JARVIS_LOCAL_PROVIDER_MODE=http
export JARVIS_LOCAL_ENDPOINT=http://localhost:8080
export JARVIS_LOCAL_MODEL_NAME=llama3-8b-q4
export JARVIS_LOCAL_PROVIDER_TIMEOUT=120     # Pi is slower; give it time
```

### Performance notes for Pi

- Use Q4_K_M quantisation (best balance of quality and speed).
- `JARVIS_SANDBOX_TIMEOUT` may need to be raised to `15.0` on Pi 4.
- Disable web research on Pi unless you have a good network connection.
- The web interface can run on a separate machine — only the API server
  and Python agent need to be on the Pi.

### Accessing from iPhone over LAN

```bash
# On Pi — find its IP
hostname -I

# Start the API server bound to all interfaces
PORT=3001 pnpm --filter @workspace/api-server dev

# On iPhone — open the web interface URL:
# http://<pi-ip>:5173  (Vite dev server)
# or build for production:
pnpm --filter @workspace/jarvis-interface build
npx serve artifacts/jarvis-interface/dist -p 5173 -s
```

---

## Provider swap guide

All providers implement the same `Brain` protocol (`jarvis/agent/brain.py`).
Swapping one for another requires only environment variable changes — no code edits.

| Scenario | Change |
|---|---|
| OpenAI → Anthropic | `JARVIS_LLM_PROVIDER=anthropic`, update model name |
| OpenAI → Groq | `JARVIS_LLM_PROVIDER=groq`, e.g. `JARVIS_LLM_MODEL=llama-3.3-70b-versatile` |
| Remote → Ollama | Disable LLM, enable local provider |
| Remote → llama.cpp | Same as Ollama, different endpoint/port |
| Any → Demo | `JARVIS_DEMO_MODE=true` overrides everything |

## STT / TTS swap guide

Voice is implemented entirely in the browser (`src/hooks/use-voice.ts`) using
the Web Speech API.  To swap providers:

1. Replace the `_fetch_url` and synthesis calls inside `use-voice.ts` with
   calls to your preferred provider (e.g. Whisper, ElevenLabs, Google Cloud TTS).
2. No Python changes are needed — the voice pipeline does not cross the API boundary.
3. For cloud STT/TTS on Raspberry Pi, set up a proxy endpoint on the Pi so the
   browser can send audio to it over LAN.

## What remains for the future

| Feature | Status |
|---|---|
| Real-time streaming responses | Not yet — single call/response per goal |
| Persistent episodic memory across restarts | ✅ Done (tiered MemoryStore) |
| Local LLM on Pi (llama.cpp) | Supported via `LocalAIProvider` |
| Mobile microphone → Pi STT → on-device Whisper | Not yet |
| Self-improvement with approval | Architecture in place; UI pending |
| Security assessment from UI | Architecture in place; UI pending |
