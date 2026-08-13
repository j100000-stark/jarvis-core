---
name: Structured error pipeline
description: How execution failures are classified, sanitized, and surfaced from Python to the browser.
---

## The problem that was fixed
`execute_goal_structured()` had a broad `except Exception` that returned only `"Goal execution failed (1). The incident was recorded locally."` — no type, no component, no recoverability hint.

## Architecture

### Python — `jarvis/diagnostics.py`
- `sanitize_message(text)` / `sanitize_trace(trace)` — regex + env-var-value redaction. Must be applied before any string crosses the subprocess boundary.
- `build_execution_error(incident, *, goal, failing_step)` — returns a sanitized dict with: `code`, `type`, `message`, `component`, `step`, `recoverable`, `incidentId`, `operation`, `timestamp`. Never includes raw traceback.
- Component is inferred from `error_type` first (`BrainUnavailableError` → `brain`, `RemoteLLMConfigError` → `brain`), then from `operation` prefix (`step:…` / `retry:…` → `executor`, `execute_goal_structured` → `assistant`).
- `BrainUnavailableError`, `RemoteLLMConfigError`, `LocalProviderConfigError`, `SystemExit` → `recoverable=False`. Everything else → `recoverable=True`.

### `jarvis/core/assistant.py` — `execute_goal_structured` except block
Returns `"error": exec_error` alongside the existing `"failure"` string. Both are sanitized.
Also scans `recovery._incidents` for the innermost `step:…` / `retry:…` incident to derive `failing_step`.

### Type chain (all files were updated)
1. `lib/api-zod/src/generated/api.ts` — Zod schema: `error: zod.object({...}).optional().nullable()`
2. `lib/api-zod/src/generated/types/jarvisExecutionDiagnostic.ts` — NEW TS interface
3. `lib/api-zod/src/generated/types/jarvisMessageResponse.ts` — added `error?: JarvisExecutionDiagnostic | null`
4. `lib/api-client-react/src/generated/api.schemas.ts` — added `JarvisExecutionDiagnostic` interface and `error?` to `JarvisMessageResponse`
5. `artifacts/api-server/src/lib/jarvis-runtime.ts` — `ExecutionDiagnostic` type + `error?` on `JarvisGoalResult`

**Why**: Zod `.parse()` in the route strips unknown keys by default, so `error` must be in the Zod schema or it will be dropped before reaching the browser.

**dist declaration lag**: `lib/api-client-react` has `dist/*.d.ts` declaration files that don't auto-rebuild. The jarvis-interface tsconfig uses project references so it picks up dist. Workaround in `home.tsx`: `(result as typeof result & { error?: ExecutionDiagnostic | null }).error`. Remove this cast once the dist files are regenerated.

### Frontend
- `artifacts/jarvis-interface/src/components/jarvis/error-detail-card.tsx` — NEW. Exports `ExecutionDiagnostic` interface (shared via import in `chat-sheet.tsx`). Collapsed: pill with code + component. Expanded: message, type, component, step, incident ID, recovery hint (amber=recoverable, red=not).
- `chat-sheet.tsx` `Message` interface: added `error?: ExecutionDiagnostic | null`.
- `home.tsx`: on `onSuccess` with `result.error` present → pushLine `❌ ERROR`, COMPONENT, STEP, RECOVERY, then `setTimeout(800)` pushLine RECOVERY FAILED, `setLastError`, `pushAlert`, `triggerAlertPulse`. `<ErrorDetailCard>` rendered between alerts and response card.

## Test coverage
`tests/test_diagnostics.py` — 44 tests, unittest only (no pytest). Covers: sanitize_message (8), sanitize_trace (3), build_execution_error (27), integration with assistant (6).

**Why**: `_make_assistant()` uses `Assistant.__new__` + manual attribute setting. Must include `assistant.sandbox = MagicMock()` because `run_goal` passes `sandbox=self.sandbox` into `ToolContext`.
