---
name: Cinematic UI V2 — Operating Console
description: Full cinematic redesign of home.tsx to an AI operating console. New components and layout described here.
---

## New components (artifacts/jarvis-interface/src/components/jarvis/)
- `live-terminal.tsx` — `LiveTerminal`, `mkLine`, `termLine`, `TerminalLine`, `TerminalSeverity` types. Severity colors: normal=blue/cyan, info=light-blue, success=cyan-green, warning=amber, error=red, critical=bright-red, recovery=amber. Older lines fade to opacity 0.18.
- `alert-card.tsx` — `AlertCard`, `mkAlert`, `AlertEntry`, `AlertSeverity`. Three severities: warning/error/critical. Each is a floating compact card — never full-screen. Dismissible.
- `response-card.tsx` — `ResponseCard`. Auto-collapses on new message. Shows latest assistant message inline below terminal.

## Layout (portrait)
1. header (top bar): J· logo + JARVIS, mode badge (REAL LLM/DEMO/LOCAL LLM), connection dot, shield button
2. main: NeuralCore (coreSize = min(window.innerWidth-40, 340)), no flex:1
3. state chip: ● STANDBY / LISTENING / etc.
4. terminal container: flex:1 so it fills remaining space; LiveTerminal inside with maxHeight:160
5. alerts: float here if any
6. response card: float here after first message
7. nav (bottom): 3 icon buttons (Chat/Mic/System) with tiny labels — mic has no "TAP TO SPEAK" text

## Terminal event system (home.tsx)
- `pushLine(key, value, severity)` → appends to `termLines` state (max 120)
- Boot sequence fires once when runtime.connected becomes true (hasBootedRef guards re-runs)
- Transitions tracked via prevXxxRef refs compared inside useEffects
- Voice pipeline events: mic active → INPUT RECEIVED → SPEECH TRANSCRIBED → (model) PROCESSING → RESPONSE GENERATED → (ELEVENLABS SYNTHESIS) → AUDIO STREAMING → JARVIS SPEAKING → JARVIS IDLE
- Demo events prefixed with [DEMO]

## Alert/pulse system (home.tsx)
- `pushAlert(title, body, severity)` → appends to `alerts` state
- `triggerAlertPulse()` → sets `alertPulse` true for 4 s, which causes NeuralCore to show 'alert' state
- `alertPulse` is lowest priority in deriveCoreState — only active when idle
- Auto-alerts: runtime offline, send error, health check failure, voice error

## CoreState derivation priority
offline > listening > speaking > thinking > alert > idle

**Why:** alert is transient (4s) and should not override active voice/LLM states.

## No text labels on mic button
Mic button in bottom nav has no label text. State label lives in the state chip above the terminal, not on the button.

## Screenshot notes
Startup animation takes 3.5s. Screenshots taken at page load show phase 1 (tiny blue dot). Full neural network visible after 3.5s — this is correct designed behavior.
