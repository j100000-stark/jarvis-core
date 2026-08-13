---
name: Voice hook
description: useVoice hook using Web Speech API — type declarations, state machine, auto-send pattern.
---

## File
`artifacts/jarvis-interface/src/hooks/use-voice.ts`

## Key decisions

### Self-declared types
TypeScript's lib.dom.d.ts does NOT reliably expose SpeechRecognition / SpeechRecognitionEvent / SpeechRecognitionErrorEvent in all tsconfig targets. The hook declares its own interfaces (ISpeechRecognition, SpeechRecognitionEvent, etc.) to avoid import errors.

### isSupportedBrowser
Computed once at module load. All methods check `isSupportedBrowser` and return early if false. Callers see `isSupported: false` and can show fallback UI.

### speak() pattern
Always cancels recognition before speaking (prevents mic feedback loop). Sets voiceState to 'speaking' synchronously, then lets utterance.onend reset to 'idle'.

### Auto-send pattern in home.tsx
voice2.onTranscript sets `goal` and `lastTranscriptRef.current`. A useEffect watches `goal` and auto-sends when `goal === lastTranscriptRef.current` (typed goals don't match because lastTranscriptRef isn't updated by the text input).

### Two useVoice instances problem
home.tsx originally instantiated useVoice twice (bug). Fixed: single instance `voice2` used throughout.

## State machine
idle → listening (startListening)
listening → idle (stopListening or final result)
idle → speaking (speak)
speaking → idle (utterance.onend)
any → error (recognition/synthesis error)
unsupported (browser doesn't support API)

**Why:** Web Speech API is browser-native, no API key, works on iPhone Safari (iOS 16+). Provider-agnostic so ElevenLabs/Whisper can replace it later.
