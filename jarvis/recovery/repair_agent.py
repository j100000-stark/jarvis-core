"""RepairAgent — a dedicated engineering-recovery agent, separate from main JARVIS.

Architecture (spec Phase 7):

    MAIN JARVIS ── incident ──▶ REPAIR AGENT
                                   │ inspect → diagnose → plan
                                   │ checkpoint → patch → test → verify
                                   ├─ success  → retry signal
                                   └─ failure  → rollback → report

Model configuration is independent from the main brain:
    REPAIR_LLM_PROVIDER  (defaults to JARVIS_LLM_PROVIDER)
    REPAIR_LLM_MODEL     (defaults to JARVIS_LLM_MODEL)
The current strategies are deterministic (no LLM call is required), but the
architecture reserves an independent model slot for future LLM-driven repair.

Safety constraints (never relaxed):
  - Bounded: max 3 repair attempts per incident/goal.
  - Transactional: files are checkpointed before patching; verification
    failure triggers rollback to the checkpoint.
  - Never touches secrets: config repairs go through ConfigStore which
    rejects secret-looking keys; incident records pass sanitize_message().
  - Only whitelisted files may be patched (config overlay + data files).
  - Never claims success without a verification step passing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

_MAX_ATTEMPTS = 3

# Files the RepairAgent is allowed to modify. Everything else is off-limits.
_PATCHABLE_ALLOWLIST = (
    "data/runtime_config.json",
    "data/memory.json",
)


@dataclass(slots=True)
class RepairIncident:
    """Full audit record for one repair lifecycle (spec Phase 9)."""

    incident_id: int
    timestamp: str
    component: str
    error_category: str
    root_cause: str = ""
    repair_plan: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    tests_executed: list[str] = field(default_factory=list)
    test_results: str = ""
    verification_result: str = ""
    rollback_result: str = ""
    retry_result: str = ""
    stages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "incidentId": self.incident_id,
            "timestamp": self.timestamp,
            "component": self.component,
            "errorCategory": self.error_category,
            "rootCause": self.root_cause,
            "repairPlan": self.repair_plan,
            "filesChanged": self.files_changed,
            "testsExecuted": self.tests_executed,
            "testResults": self.test_results,
            "verificationResult": self.verification_result,
            "rollbackResult": self.rollback_result,
            "retryResult": self.retry_result,
            "stages": self.stages,
        }


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    """Result of a full RepairAgent lifecycle run."""

    success: bool
    incident: RepairIncident
    # Signals the caller should retry the failed operation.
    should_retry: bool = False
    message: str = ""


class RepairAgent:
    """Engineering-recovery agent with a transactional patch/verify/rollback loop."""

    def __init__(self, data_dir: Path, workspace_root: Path | None = None) -> None:
        self._data_dir = Path(data_dir)
        self._root = workspace_root or Path.cwd()
        self._checkpoint_dir = self._data_dir / "repair_checkpoints"
        self._incident_file = self._data_dir / "repair_agent_incidents.json"
        self._attempts_by_key: dict[str, int] = {}
        self._next_id = self._load_next_id()

    # ── Model configuration (independent from main brain) ──────────────────

    @staticmethod
    def model_config() -> dict[str, str]:
        """Return the repair model configuration (spec Phase 7).

        Falls back to the main JARVIS model when no dedicated repair model
        is configured.  Secrets are never returned here.
        """
        return {
            "provider": os.environ.get(
                "REPAIR_LLM_PROVIDER", os.environ.get("JARVIS_LLM_PROVIDER", "groq")
            ),
            "model": os.environ.get(
                "REPAIR_LLM_MODEL", os.environ.get("JARVIS_LLM_MODEL", "openai/gpt-oss-120b")
            ),
        }

    # ── Public API ──────────────────────────────────────────────────────────

    def run_repair(
        self,
        *,
        component: str,
        error_category: str,
        root_cause: str,
        repair_plan: list[str],
        patch: Callable[[], list[str]],
        verify: Callable[[], bool],
        test_command: list[str] | None = None,
        attempt_key: str | None = None,
    ) -> RepairOutcome:
        """Run the full lifecycle: checkpoint → patch → test → verify → (rollback).

        ``patch``  applies the change and returns the list of files it touched
                   (must all be inside the allowlist).
        ``verify`` returns True when the repaired behaviour is confirmed.
        ``test_command`` optionally runs a focused test module (e.g.
                   [sys.executable, "-m", "unittest", "tests.test_x"]).

        The repair is only reported successful when tests (if any) pass AND
        verification passes.  On any failure the checkpoint is rolled back.
        """
        key = attempt_key or f"{component}:{error_category}"
        attempts = self._attempts_by_key.get(key, 0)
        incident = RepairIncident(
            incident_id=self._next_id,
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
            component=component,
            error_category=error_category,
            root_cause=root_cause,
            repair_plan=list(repair_plan),
        )
        self._next_id += 1

        if attempts >= _MAX_ATTEMPTS:
            incident.stages.append("BLOCKED: max attempts reached")
            incident.verification_result = "skipped"
            self._record(incident)
            return RepairOutcome(
                success=False,
                incident=incident,
                message=f"Repair limit ({_MAX_ATTEMPTS}) reached for {key}.",
            )
        self._attempts_by_key[key] = attempts + 1

        incident.stages.append("INCIDENT DETECTED")
        incident.stages.append(f"DIAGNOSIS: {error_category}")
        incident.stages.append(f"ROOT CAUSE: {root_cause}")
        incident.stages.append("REPAIR PLAN CREATED")

        # ── Checkpoint ────────────────────────────────────────────────────
        checkpoint = self._create_checkpoint(incident.incident_id)
        incident.stages.append("CHECKPOINT CREATED")

        # ── Patch ─────────────────────────────────────────────────────────
        try:
            changed = patch()
        except Exception as patch_error:  # noqa: BLE001
            incident.stages.append("PATCH FAILED")
            incident.rollback_result = self._rollback(checkpoint)
            incident.stages.append("ROLLBACK")
            self._record(incident)
            return RepairOutcome(
                success=False,
                incident=incident,
                message=f"Patch failed: {self._sanitize(str(patch_error))}",
            )

        illegal = [f for f in changed if not self._is_patchable(f)]
        if illegal:
            incident.stages.append(f"PATCH REJECTED: touched non-allowlisted files {illegal}")
            incident.rollback_result = self._rollback(checkpoint)
            incident.stages.append("ROLLBACK")
            self._record(incident)
            return RepairOutcome(
                success=False,
                incident=incident,
                message=f"Patch touched files outside the allowlist: {illegal}",
            )

        incident.files_changed = list(changed)
        incident.stages.append("PATCH APPLIED")

        # ── Test ──────────────────────────────────────────────────────────
        if test_command:
            incident.tests_executed.append(" ".join(test_command))
            ok, summary = self._run_tests(test_command)
            incident.test_results = summary
            if not ok:
                incident.stages.append("TEST FAILED")
                incident.rollback_result = self._rollback(checkpoint)
                incident.stages.append("ROLLBACK")
                self._record(incident)
                return RepairOutcome(
                    success=False, incident=incident,
                    message=f"Repair tests failed: {summary}",
                )
            incident.stages.append("TESTS PASSED")

        # ── Verify ────────────────────────────────────────────────────────
        try:
            verified = bool(verify())
        except Exception as verify_error:  # noqa: BLE001
            verified = False
            incident.verification_result = f"exception: {self._sanitize(str(verify_error))}"

        if not verified:
            if not incident.verification_result:
                incident.verification_result = "failed"
            incident.stages.append("VERIFICATION FAILED")
            incident.rollback_result = self._rollback(checkpoint)
            incident.stages.append("ROLLBACK")
            self._record(incident)
            return RepairOutcome(
                success=False, incident=incident,
                message="Verification failed — changes rolled back.",
            )

        incident.verification_result = "passed"
        incident.stages.append("VERIFICATION PASSED")
        incident.retry_result = "retry signalled"
        incident.stages.append("RETRY SIGNALLED")
        self._record(incident)
        self._cleanup_checkpoint(checkpoint)
        return RepairOutcome(
            success=True, incident=incident, should_retry=True,
            message="Repair verified. Retrying original operation.",
        )

    def reset_attempts(self) -> None:
        self._attempts_by_key.clear()

    def incidents(self) -> list[dict]:
        try:
            data = json.loads(self._incident_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    # ── Internals ─────────────────────────────────────────────────────────

    def _is_patchable(self, file_path: str) -> bool:
        try:
            rel = str(Path(file_path).resolve().relative_to(self._root.resolve()))
        except ValueError:
            return False
        return rel in _PATCHABLE_ALLOWLIST

    def _create_checkpoint(self, incident_id: int) -> Path:
        """Snapshot patchable files AND the JARVIS_*/REPAIR_* environment so a
        failed repair can be rolled back transactionally (files + process env)."""
        cp = self._checkpoint_dir / f"incident_{incident_id}"
        cp.mkdir(parents=True, exist_ok=True)
        for rel in _PATCHABLE_ALLOWLIST:
            src = self._root / rel
            if src.exists():
                dst = cp / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        env_snapshot = {
            k: v for k, v in os.environ.items()
            if k.startswith("JARVIS_") or k.startswith("REPAIR_")
        }
        (cp / "_env_snapshot.json").write_text(
            json.dumps(env_snapshot), encoding="utf-8"
        )
        return cp

    def _rollback(self, checkpoint: Path) -> str:
        """Restore checkpointed files AND environment. Returns a result summary."""
        restored: list[str] = []
        try:
            # Environment first: undo any os.environ mutations the patch made.
            env_file = checkpoint / "_env_snapshot.json"
            if env_file.exists():
                snapshot = json.loads(env_file.read_text(encoding="utf-8"))
                for key in [
                    k for k in os.environ
                    if (k.startswith("JARVIS_") or k.startswith("REPAIR_"))
                    and k not in snapshot
                ]:
                    os.environ.pop(key, None)
                os.environ.update(snapshot)
                restored.append("environment")
            for rel in _PATCHABLE_ALLOWLIST:
                snap = checkpoint / rel
                target = self._root / rel
                if snap.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(snap, target)
                    restored.append(rel)
                elif target.exists():
                    # File was created by the patch; remove it to restore state.
                    target.unlink()
                    restored.append(f"{rel} (removed)")
            return f"restored: {', '.join(restored) or 'nothing to restore'}"
        except OSError as error:
            return f"rollback error: {self._sanitize(str(error))}"

    def _cleanup_checkpoint(self, checkpoint: Path) -> None:
        shutil.rmtree(checkpoint, ignore_errors=True)

    def _run_tests(self, command: list[str]) -> tuple[bool, str]:
        try:
            proc = subprocess.run(  # noqa: S603
                command, capture_output=True, text=True, timeout=120,
                cwd=self._root,
            )
        except (subprocess.TimeoutExpired, OSError) as error:
            return False, f"test runner error: {self._sanitize(str(error))}"
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        summary = self._sanitize(" | ".join(tail[-3:])[:300])
        return proc.returncode == 0, summary

    @staticmethod
    def _sanitize(text: str) -> str:
        try:
            from ..diagnostics import sanitize_message
            return sanitize_message(text)
        except Exception:  # noqa: BLE001
            return text

    def _load_next_id(self) -> int:
        records = self.incidents()
        if not records:
            return 1
        return max((r.get("incidentId", 0) for r in records), default=0) + 1

    def _record(self, incident: RepairIncident) -> None:
        # Sanitize EVERY persisted string field — audit records must never
        # carry secret-bearing error text regardless of which caller built them.
        incident.root_cause = self._sanitize(incident.root_cause)
        incident.repair_plan = [self._sanitize(s) for s in incident.repair_plan]
        incident.stages = [self._sanitize(s) for s in incident.stages]
        incident.test_results = self._sanitize(incident.test_results)
        incident.verification_result = self._sanitize(incident.verification_result)
        incident.rollback_result = self._sanitize(incident.rollback_result)
        records = self.incidents()
        records.append(incident.to_dict())
        self._incident_file.parent.mkdir(parents=True, exist_ok=True)
        self._incident_file.write_text(
            json.dumps(records[-50:], indent=2), encoding="utf-8"
        )


def python_test_command(module: str) -> list[str]:
    """Build a focused unittest command for a single test module."""
    return [sys.executable, "-m", "unittest", module, "-v"]
