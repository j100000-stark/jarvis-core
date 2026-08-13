---
name: Wake word + mic permission + TTS categories
description: Frontend voice architecture decisions from the Siri-like phase
---

- Mic permission is requested proactively on app open (`initMicrophone()` in use-voice.ts): Permissions API first (no re-prompt after deny), then getUserMedia with tracks stopped immediately. Terminal shows MICROPHONE READY / PERMISSION DENIED.
- Wake word (`use-wake-word.ts`): continuous SpeechRecognition loop, local only — no audio to our server. Regex tolerates mis-transcriptions (jarvys/jervis) and strips the wake phrase; remainder auto-submits as the command. `stop()` is called BEFORE onWake so command STT is the single mic owner.
- Honest degradation: sessions ending <2 s count as failures; after 4, status → "restricted" (typical iOS Safari) and terminal says USE MIC BUTTON. Backoff is capped exponential (max 5 s). Never fake an active wake state.
- Duplicate-submission guard in use-voice onend: identical text within 3 s is dropped (Safari double-onend artifact).
- TTS failure categories (TTS_AUTH_FAILED, TTS_VOICE_NOT_FOUND, ...) come from /api/tts error JSON; the browser-synthesis fallback ALWAYS surfaces the real category to the terminal first. audio.onerror also routes through the shared `speakWithBrowser` fallback.
- `/api/tts/health` does a REAL ElevenLabs synthesis; results cached in-process (10 min success / 60 s failure) to bound paid-API cost. Boot terminal line ELEVENLABS VERIFIED/<category> comes from it — never hardcoded READY.
- Known env fact (Aug 2026): the ElevenLabs account is free-tier with a library voice → API returns 402 paid_plan_required (TTS_UPSTREAM_ERROR). User action: upgrade plan or set ELEVENLABS_VOICE_ID to a premade voice. Do not silently swap voice IDs.
