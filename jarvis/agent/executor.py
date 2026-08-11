"""Plan execution, verification, bounded retries, and failure reporting."""

from __future__ import annotations

from ..recovery import RecoveryManager
from ..tools import ToolContext, ToolRegistry
from .models import ExecutionReport, Plan, StepReport, StepStatus, ToolResult


class AgentExecutor:
    """Execute a brain-produced plan only through the registered tool boundary."""

    def __init__(
        self,
        registry: ToolRegistry,
        recovery: RecoveryManager,
    ) -> None:
        self.registry = registry
        self.recovery = recovery

    def execute(self, plan: Plan, context: ToolContext) -> ExecutionReport:
        reports: list[StepReport] = []
        for step in plan.steps:
            attempts = 0
            final_result = ToolResult(ok=False, error="Step was not attempted.")
            verified = False
            while attempts <= step.max_retries:
                attempts += 1
                try:
                    final_result = self.registry.execute(
                        step.tool_name, step.argument, context
                    )
                    verified = self.registry.verify(step.tool_name, final_result, step)
                except Exception as error:
                    self.recovery.record(error, operation=f"step:{step.identifier}")
                    final_result = ToolResult(ok=False, error=str(error))
                    verified = False

                if final_result.ok and verified:
                    break

                if attempts <= step.max_retries:
                    self.recovery.record(
                        RuntimeError(final_result.error or "Tool verification failed."),
                        operation=f"retry:{step.identifier}",
                    )

            status = StepStatus.SUCCEEDED if final_result.ok and verified else StepStatus.FAILED
            report = StepReport(step, status, attempts, final_result, verified)
            reports.append(report)
            if status is StepStatus.FAILED:
                return ExecutionReport(
                    goal=plan.goal,
                    success=False,
                    steps=tuple(reports),
                    failure=final_result.error
                    or f"Verification failed for step '{step.identifier}'.",
                )

        return ExecutionReport(plan.goal, True, tuple(reports))
