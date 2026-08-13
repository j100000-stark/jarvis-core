"""CodeRepairPipeline — safe, AI-assisted source-code repair (spec §7).

Pipeline (every stage recorded; nothing is ever blindly applied):

    failure
      → diagnosis
      → identify relevant files
      → generate proposed patch      (pluggable repair model)
      → validate patch               (allowlist + syntax before touching disk)
      → run tests / type checks
      → apply patch ONLY if validation succeeds
      → runtime verification (caller-supplied)
      → record incident

Safety constraints (never relaxed):
  - The repair model NEVER overwrites arbitrary files: patches are only
    accepted for files inside the configured allowlist roots.
  - Python patches must parse (AST) BEFORE anything is written to disk.
  - Dry-run mode returns the proposed patch without applying anything.
  - Tests (when configured) must pass on the patched tree or the patch is
    rolled back completely.
  - Secrets are never read, written, or included in incident records.

Model configuration (environment):
  REPAIR_LLM_PROVIDER / REPAIR_LLM_MODEL select the dedicated repair model
  (fall back to JARVIS_LLM_* — see repair_agent.py).  The primary JARVIS
  model remains responsible for normal reasoning; the repair model is only
  invoked here.  The generator is injected as a callable so tests and future
  providers never require live network access.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# A patch proposal: relative file path → complete new file content.
PatchProposal = dict[str, str]
# Generator signature: (diagnosis, {path: current_content}) -> PatchProposal
PatchGenerator = Callable[[str, dict[str, str]], PatchProposal]

_ALLOWED_SUFFIXES = {".py", ".ts", ".tsx", ".json", ".md"}
_FORBIDDEN_PARTS = {".env", "secrets", ".git"}


def _sanitize(text: str) -> str:
    """Redact anything that looks like a secret/token before persistence."""
    try:
        from ..diagnostics import _redact_env_values  # type: ignore[attr-defined]
        text = _redact_env_values(text)
    except Exception:
        pass
    return re.sub(r"[A-Za-z0-9_\-]{32,}", "[REDACTED]", text)


@dataclass(frozen=True, slots=True)
class CodeRepairReport:
    """Complete, honest record of one code-repair run."""

    success: bool
    dry_run: bool
    applied: bool
    diagnosis: str
    files_involved: tuple[str, ...]
    proposed_patch: dict[str, str]  # sanitized: content lengths only in incidents
    validation_errors: tuple[str, ...]
    tests_run: tuple[str, ...]
    test_results: str
    message: str
    stages: tuple[str, ...] = ()
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )


class CodeRepairPipeline:
    """Orchestrates safe AI-assisted repair of broken source files."""

    def __init__(
        self,
        *,
        project_root: Path,
        data_dir: Path,
        generator: PatchGenerator | None = None,
        allowed_roots: tuple[str, ...] = ("jarvis",),
        test_command: tuple[str, ...] | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self._root = project_root.resolve()
        self._data_dir = data_dir
        self._generator = generator
        self._allowed_roots = allowed_roots
        self._test_command = test_command
        # Dedicated repair model config — NEVER the primary reasoning model.
        self._provider = provider or os.environ.get(
            "REPAIR_LLM_PROVIDER", os.environ.get("JARVIS_LLM_PROVIDER", "")
        )
        self._model = model or os.environ.get(
            "REPAIR_LLM_MODEL", os.environ.get("JARVIS_LLM_MODEL", "")
        )

    # ── Public API ──────────────────────────────────────────────────────────

    def repair(
        self,
        *,
        failure_message: str,
        relevant_files: list[str],
        dry_run: bool | None = None,
        verify: Callable[[], bool] | None = None,
    ) -> CodeRepairReport:
        """Run the full pipeline.  ``dry_run`` defaults to REPAIR_DRY_RUN env."""
        if dry_run is None:
            dry_run = os.environ.get("REPAIR_DRY_RUN", "").lower() in ("1", "true", "yes")
        stages: list[str] = ["FAILURE_DETECTED", "DIAGNOSIS"]
        diagnosis = "Code repair requested for failure: " + _sanitize(failure_message[:300])

        # ── Identify relevant files ────────────────────────────────────────
        stages.append("IDENTIFY_FILES")
        files, file_errors = self._load_files(relevant_files)
        if file_errors:
            return self._finish(
                success=False, dry_run=dry_run, applied=False, diagnosis=diagnosis,
                files=tuple(files), patch={}, validation_errors=tuple(file_errors),
                tests=(), test_results="", stages=tuple(stages),
                message="File identification failed: " + "; ".join(file_errors),
            )

        # ── Generate proposed patch ────────────────────────────────────────
        stages.append("GENERATE_PATCH")
        if self._generator is None:
            return self._finish(
                success=False, dry_run=dry_run, applied=False, diagnosis=diagnosis,
                files=tuple(files), patch={}, validation_errors=(
                    "No repair model generator configured "
                    f"(provider={self._provider or 'unset'}, model={self._model or 'unset'}).",
                ),
                tests=(), test_results="", stages=tuple(stages),
                message="No repair model configured — nothing was changed.",
            )
        try:
            proposal = self._generator(diagnosis, files)
        except Exception as exc:  # noqa: BLE001 — must never crash the host
            return self._finish(
                success=False, dry_run=dry_run, applied=False, diagnosis=diagnosis,
                files=tuple(files), patch={}, validation_errors=(
                    f"Patch generation failed: {type(exc).__name__}",
                ),
                tests=(), test_results="", stages=tuple(stages),
                message="Repair model failed to produce a patch — nothing was changed.",
            )

        # ── Validate patch BEFORE any disk write ───────────────────────────
        stages.append("VALIDATE_PATCH")
        validation_errors = self._validate(proposal)
        # The repair model may only touch the files identified during
        # diagnosis — never other allowlisted files.
        for rel in proposal:
            if rel not in files:
                validation_errors.append(
                    f"Patch touches file outside the identified set: {rel}"
                )
        if validation_errors:
            return self._finish(
                success=False, dry_run=dry_run, applied=False, diagnosis=diagnosis,
                files=tuple(files), patch=proposal,
                validation_errors=tuple(validation_errors),
                tests=(), test_results="", stages=tuple(stages),
                message="Patch validation failed — nothing was applied.",
            )

        if dry_run:
            stages.append("DRY_RUN_COMPLETE")
            return self._finish(
                success=True, dry_run=True, applied=False, diagnosis=diagnosis,
                files=tuple(files), patch=proposal, validation_errors=(),
                tests=(), test_results="", stages=tuple(stages),
                message="Dry run: patch validated but NOT applied.",
            )

        # A patch is only ever APPLIED when at least one verification
        # mechanism (tests and/or runtime verification) can gate it.
        if self._test_command is None and verify is None:
            return self._finish(
                success=False, dry_run=False, applied=False, diagnosis=diagnosis,
                files=tuple(files), patch=proposal, validation_errors=(
                    "No verification mechanism configured (tests or runtime verify).",
                ),
                tests=(), test_results="", stages=tuple(stages),
                message=(
                    "Patch validated but NOT applied — a test command or runtime "
                    "verification is required before any apply. Use dry_run to inspect."
                ),
            )

        # ── Apply (with full rollback snapshot taken from DISK) ────────────
        stages.append("APPLY_PATCH")
        snapshot: dict[str, str | None] = {}
        for rel in proposal:
            target = self._root / rel
            snapshot[rel] = (
                target.read_text(encoding="utf-8") if target.exists() else None
            )
        for rel, content in proposal.items():
            target = self._root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        # ── Tests / type checks ────────────────────────────────────────────
        tests_run: tuple[str, ...] = ()
        test_results = "no test command configured"
        if self._test_command:
            stages.append("RUN_TESTS")
            tests_run = (" ".join(self._test_command),)
            ok, test_results = self._run_tests()
            if not ok:
                self._rollback(snapshot)
                stages.append("ROLLBACK")
                return self._finish(
                    success=False, dry_run=False, applied=False, diagnosis=diagnosis,
                    files=tuple(files), patch=proposal, validation_errors=(),
                    tests=tests_run, test_results=test_results, stages=tuple(stages),
                    message="Tests failed on patched tree — patch rolled back.",
                )

        # ── Runtime verification ───────────────────────────────────────────
        if verify is not None:
            stages.append("RUNTIME_VERIFICATION")
            try:
                verified = bool(verify())
            except Exception:
                verified = False
            if not verified:
                self._rollback(snapshot)
                stages.append("ROLLBACK")
                return self._finish(
                    success=False, dry_run=False, applied=False, diagnosis=diagnosis,
                    files=tuple(files), patch=proposal, validation_errors=(),
                    tests=tests_run, test_results=test_results, stages=tuple(stages),
                    message="Runtime verification failed — patch rolled back.",
                )

        stages.append("RECORDED")
        return self._finish(
            success=True, dry_run=False, applied=True, diagnosis=diagnosis,
            files=tuple(files), patch=proposal, validation_errors=(),
            tests=tests_run, test_results=test_results, stages=tuple(stages),
            message="Patch validated, applied, and verified.",
        )

    # ── Internals ───────────────────────────────────────────────────────────

    def _load_files(self, rel_paths: list[str]) -> tuple[dict[str, str], list[str]]:
        files: dict[str, str] = {}
        errors: list[str] = []
        for rel in rel_paths:
            err = self._path_error(rel)
            if err:
                errors.append(err)
                continue
            p = self._root / rel
            files[rel] = p.read_text(encoding="utf-8") if p.exists() else ""
        return files, errors

    def _path_error(self, rel: str) -> str | None:
        p = Path(rel)
        if p.is_absolute() or ".." in p.parts:
            return f"Path escapes project root: {rel}"
        # Symlink containment: the RESOLVED path must stay inside the root.
        try:
            resolved = (self._root / p).resolve()
            if not resolved.is_relative_to(self._root):
                return f"Resolved path escapes project root: {rel}"
        except OSError:
            return f"Unresolvable path: {rel}"
        if any(part.lower() in _FORBIDDEN_PARTS for part in p.parts) or p.name.startswith(".env"):
            return f"Forbidden path: {rel}"
        if p.suffix not in _ALLOWED_SUFFIXES:
            return f"Disallowed file type: {rel}"
        if not any(p.parts and p.parts[0] == root for root in self._allowed_roots):
            return f"Path outside allowed roots {self._allowed_roots}: {rel}"
        return None

    def _validate(self, proposal: PatchProposal) -> list[str]:
        errors: list[str] = []
        if not proposal:
            errors.append("Empty patch proposal.")
        for rel, content in proposal.items():
            err = self._path_error(rel)
            if err:
                errors.append(err)
                continue
            if not isinstance(content, str) or not content.strip():
                errors.append(f"Empty/invalid content for {rel}")
                continue
            if rel.endswith(".py"):
                try:
                    ast.parse(content)
                except SyntaxError as exc:
                    errors.append(f"Syntax error in proposed {rel}: line {exc.lineno}")
            if rel.endswith(".json"):
                try:
                    json.loads(content)
                except Exception:
                    errors.append(f"Invalid JSON in proposed {rel}")
        return errors

    def _run_tests(self) -> tuple[bool, str]:
        try:
            proc = subprocess.run(  # noqa: S603 — fixed, configured command
                list(self._test_command or ()),
                cwd=self._root, capture_output=True, text=True, timeout=600,
            )
            tail = _sanitize((proc.stdout + proc.stderr)[-500:])
            return proc.returncode == 0, f"exit={proc.returncode}: {tail}"
        except Exception as exc:  # noqa: BLE001
            return False, f"Test run failed to execute: {type(exc).__name__}"

    def _rollback(self, snapshot: dict[str, str | None]) -> None:
        """Restore every patched file to its exact pre-apply disk state.

        ``None`` means the file did not exist before the patch (delete it);
        any string — including "" — is restored verbatim.
        """
        for rel, original in snapshot.items():
            target = self._root / rel
            if original is None:
                if target.exists():
                    target.unlink()
            else:
                target.write_text(original, encoding="utf-8")

    def _finish(self, **kw) -> CodeRepairReport:
        report = CodeRepairReport(
            success=kw["success"], dry_run=kw["dry_run"], applied=kw["applied"],
            diagnosis=kw["diagnosis"], files_involved=kw["files"],
            proposed_patch=kw["patch"], validation_errors=kw["validation_errors"],
            tests_run=kw["tests"], test_results=kw["test_results"],
            message=kw["message"], stages=kw["stages"],
        )
        self._record(report)
        return report

    def _record(self, report: CodeRepairReport) -> None:
        """Persist a sanitized incident (patch contents replaced by sizes)."""
        incident = {
            "timestamp": report.timestamp,
            "success": report.success,
            "dry_run": report.dry_run,
            "applied": report.applied,
            "diagnosis": report.diagnosis[:300],
            "files_involved": list(report.files_involved),
            "patched_files": {k: len(v) for k, v in report.proposed_patch.items()},
            "validation_errors": list(report.validation_errors),
            "tests_run": list(report.tests_run),
            "test_results": report.test_results[:300],
            "message": report.message,
            "stages": list(report.stages),
        }
        try:
            path = self._data_dir / "code_repair_incidents.json"
            existing: list[dict] = []
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(existing, list):
                        existing = []
                except Exception:
                    existing = []
            existing.append(incident)
            self._data_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(existing[-50:], indent=2), encoding="utf-8")
        except Exception:
            pass  # incident persistence must never break the pipeline
