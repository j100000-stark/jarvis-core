---
name: CoreState — all locations that must be updated
description: When adding a new CoreState value, three frontend files all require updates.
---

## CoreState values (V1)
idle | listening | thinking | executing | speaking | offline | alert

## Files that MUST ALL be updated when CoreState changes

1. `artifacts/jarvis-interface/src/components/jarvis/neural-core.tsx`
   - `CoreState` union type
   - `STATE_CONFIG: Record<CoreState, StateConfig>` — add color/glow/speed config

2. `artifacts/jarvis-interface/src/components/jarvis/waveform.tsx`
   - `STATE_AMP: Record<CoreState, number>` — amplitude 0..1
   - `STATE_COLOR: Record<CoreState, string>` — hex color

3. `artifacts/jarvis-interface/src/pages/home.tsx`
   - `STATE_META: Record<CoreState, { label, color, dim }>` — chip label and colors
   - `deriveCoreState()` — mapping from runtime state to CoreState

**Why:** All three use `Record<CoreState, ...>` which makes them exhaustive — TypeScript errors if a state is missing, but only if you run typecheck. Forgetting one causes a runtime gap.
