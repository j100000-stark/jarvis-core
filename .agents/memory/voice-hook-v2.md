---
name: Voice hook V2 — iOS STT + TTS fixes
description: Key decisions in the full rewrite of use-voice.ts covering iOS STT, deferred SPEAKING state, unlockAudio, and onTtsStage.
---

## STT — iOS Safari fix
- iOS sometimes fires `onend` without ever firing `isFinal=true` in `onresult`.
- **Fix**: accumulate final transcript in a hook-level ref (`accumulatedFinalRef`) across all `onresult` events; also track last interim (`lastInterimRef`) as a fallback.
- Submit in `onend` only: `const toSubmit = accumulated || fallback; if (toSubmit) onTranscript(toSubmit)`.
- Never submit in `onresult` directly — causes double-submission on non-iOS browsers.
- `no-speech` and `aborted` errors are normal — clear state, return to `idle`, never show error UI.

## TTS — deferred SPEAKING state
- **DO NOT** set `voiceState("speaking")` before or during the fetch.
- Set it only inside `audio.play().then(() => setVoiceState("speaking"))`.
- If `audio.play()` is rejected (iOS autoplay policy), emit `play_failed` stage and show actionable error to user.

## iOS audio unlock
- `unlockAudio()` plays a zero-length silent AudioContext buffer during a user gesture.
- Must be called **synchronously** inside the mic button click handler, before any async work starts.
- This pre-authorises future async `audio.play()` calls in the same Safari session.
- Safe no-op on non-iOS browsers — always call it on mic press regardless.

## onTtsStage callback
- Stages: `requesting → received → playing → ended` (happy path)
- Error stages: `play_failed`, `fallback` (browser SpeechSynthesis), `error`
- Host (`home.tsx`) maps each stage to a `pushLine()` terminal event for truthful real-time UI.
- `onTtsStage` ref is updated on every render so stale closure is never an issue.

**Why:** iOS Safari's autoplay policy and STT lifecycle differ significantly from desktop Chrome. Both bugs caused silent failures (no audio played, transcript never submitted) without visible errors.
