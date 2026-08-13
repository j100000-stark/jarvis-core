---
name: Self-repair system wiring
description: How SelfRepairManager integrates with Assistant and the rules around secret safety and test helpers.
---

## Field declaration (slots=True)
- `SelfRepairManager` is declared as `self_repair: SelfRepairManager = field(init=False)` in the `@dataclass(slots=True)` class.
- Initialized in `__post_init__`: `self.self_repair = SelfRepairManager(self.settings.data_dir)`.
- `reset_attempts()` must be called at the top of `execute_goal_structured()` so each new user goal gets a fresh repair budget.

## Execution flow
```
execute_goal_structured():
  self.self_repair.reset_attempts()
  try: report = self._run_goal_with_settings(goal, effective_settings)
  except: repair → if success: retry once with effective_settings = repair.repaired_settings
  if !report.success: repair semantic failure → retry once
  return result with repairNotes (sanitized)
```

## Secret safety in repairNotes
- `repair_notes` (list of strings from `RepairResult.actions`) may contain raw error messages with secrets.
- **Always** pass through `sanitize_message()` from `jarvis.diagnostics` before including in any API response.
- Applied in `_error_result()`: `clean_notes = [sanitize_message(n) for n in repair_notes]`.
- Also applied in `self_repair.py` for the "Original error:" fallback action using `_redact_env_values`.

**Why:** `repairNotes` is a new field added to the response dict. The existing `failure` and `error` fields were already sanitized by `build_execution_error`, but `repairNotes` bypassed that pipeline and leaked raw exception messages.

## Test helpers using __new__
- `_make_assistant()` in test_diagnostics.py uses `Assistant.__new__(Assistant)` to bypass `__post_init__`.
- After adding any new `field(init=False)` to the dataclass, **also add it manually** to `_make_assistant()`.
- Also add `assistant.tools = MagicMock(); assistant.tools.names = MagicMock(return_value=[])` since `diagnose_and_repair` calls `registry.names()`.

## _run_goal_with_settings pattern
- `run_goal(goal)` now delegates to `_run_goal_with_settings(goal, self.settings)`.
- `execute_goal_structured()` passes `effective_settings` (possibly patched) for retry.
- This is the only code path that builds `ToolContext`, so patched settings propagate to every tool.
