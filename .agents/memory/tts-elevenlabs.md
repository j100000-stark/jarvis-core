---
name: ElevenLabs TTS integration
description: Server-side TTS proxy — API key never touches browser; frontend fetches /api/tts and falls back to SpeechSynthesis.
---

## Architecture
- `POST /api/tts` in `artifacts/api-server/src/routes/tts.ts` — reads ELEVENLABS_API_KEY from process.env, proxies to ElevenLabs, streams audio/mpeg back.
- `jarvis/tts/` Python package — ElevenLabsTTSProvider (urllib only) + TTSProvider base + TTSError.
- `use-voice.ts` — speak() tries /api/tts first; on error falls back to browser SpeechSynthesis. Audio plays via `new Audio(blob URL)`.

## Key rules
- API key NEVER in frontend. Only in Node.js process.env.
- ELEVENLABS_MODEL defaults to `eleven_flash_v2_5` if env var missing.
- Text cleaned (markdown stripped) before sending — both in Node route and Python class.
- `cleanForSpeech()` is exported from use-voice.ts for use by callers.
- `ttsProvider` field on UseVoice tells callers which path was used: 'elevenlabs' | 'browser' | 'none'.
- `audioRef` tracks active `<audio>` element; `stopAudio()` callback releases blob URL.

## ElevenLabs streaming endpoint
`/v1/text-to-speech/{voice_id}/stream` — returns audio/mpeg stream directly.
Voice settings: stability 0.5, similarity_boost 0.75.

## Secret isolation
Python `ElevenLabsTTSProvider` stores key as `__api_key` (name-mangled). No `api_key` public attr. repr() shows only configured/voice_id/model_id. Tests verify this.

## Test file
`tests/test_elevenlabs_tts.py` — 37 tests across 8 categories. urllib header capitalisation: xi-api-key → Xi-api-key (tested with capitalised form).

**Why:** API key must never leave the server. Fallback ensures voice works even if ElevenLabs quota exhausted or misconfigured.
