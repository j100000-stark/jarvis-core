---
name: Wake word + mic permission + TTS categories
description: Frontend voice architecture decisions from the Siri-like phase
---

- Mic permission is requested proactively on app open (`initMicrophone()` in use-voice.ts): Permissions API first (no re-prompt after deny), then getUserMedia with tracks stopped immediately. Terminal shows MICROPHONE READY / PERMISSION DENIED.
- Wake word (`use-wake-word.ts`): continuous SpeechRecognition loop, local only — no audio to our server. Regex tolerates mis-transcriptions (jarvys/jervis) and strips the wake phrase; remainder auto-submits as the command. `stop()` is called BEFORE onWake so command STT is the single mic owner.
- Honest degradation: sessions ending <2 s count as failures; after 4, status → "restricted" (typical iOS Safari) and terminal says USE MIC BUTTON. Backoff is capped exponential (max 5 s). Never fake an active wake state.
- Duplicate-submission guard in use-voice onend: identical text within 3 s is dropped (Safari double-onend artifact).
- TTS failure categories map upstream HTTP status per spec: 401 AUTH_FAILED, 402 QUOTA_OR_BILLING, 403 FORBIDDEN, 404 VOICE_OR_ENDPOINT_NOT_FOUND, 422 INVALID_REQUEST, 429 RATE_LIMITED, 5xx UPSTREAM_SERVER_ERROR — never generic UPSTREAM_ERROR when the status is known. Python self_repair._classify must list every category (lowercase). Browser-synthesis fallback ALWAYS surfaces the real category first; audio.onerror also routes through `speakWithBrowser`.
- Wake-word truthfulness: "WAKE WORD ACTIVE" only after the engine's real `onstart` fires (status "starting" until then); full lifecycle (RECOGNITION_CREATED/STARTED/RESULT/END/ERROR/RESTART, WAKE_WORD_DETECTED) is emitted via onLifecycle for the terminal. Wake matching runs on interim results too (iOS may never finalize); it-IT lang. Single-mic-owner rule: the mic button synchronously calls wakeWord.pause() (stop + clear failure budget, NO start) before command STT; the wake loop re-arms only via its enabled flag once voice returns to idle — never start two recognizers in one gesture.
- Command STT auto-submit: a 1.6 s silence timer (reset on every onresult) stops recognition; onend submits accumulated-final-else-interim exactly once (dup guard).
- /api/tts/health returns safe metadata only: apiKey/voiceId PRESENT|MISSING, model, statusCode. Boot "VOICE READY" is shown ONLY when the real synthesis test succeeds; otherwise "VOICE BROWSER FALLBACK ONLY".
- `/api/tts/health` does a REAL ElevenLabs synthesis; results cached in-process (10 min success / 60 s failure) to bound paid-API cost. Boot terminal line ELEVENLABS VERIFIED/<category> comes from it — never hardcoded READY.
- Known env fact (Aug 2026): the ElevenLabs account is free-tier with a library voice → API returns 402 paid_plan_required (TTS_UPSTREAM_ERROR). User action: upgrade plan or set ELEVENLABS_VOICE_ID to a premade voice. Do not silently swap voice IDs.
