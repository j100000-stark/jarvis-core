"""Adapters for a real locally hosted language model.

This module deliberately separates the JARVIS ``AIProvider`` contract from
the local model runtime. A runtime can be an HTTP service bound to loopback or
an executable process that reads a prompt from stdin and writes a response to
stdout. Neither adapter invents a response: connection, process, and schema
errors are surfaced to the caller.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..config import Settings
from .brain import BrainError
from .models import (
    CodeChange,
    CodeGenerationRequest,
    ExecutionReport,
    ImprovementProposal,
    Plan,
    PlanStep,
)


class LocalProviderError(BrainError):
    """Base error for local runtime communication or response failures."""


class LocalProviderConnectionError(LocalProviderError):
    """Raised when a local runtime cannot be reached or completes unsuccessfully."""


class LocalProviderResponseError(LocalProviderError):
    """Raised when a local runtime returns invalid or incomplete JSON."""


class LocalModelTransport(Protocol):
    """Transport contract implemented by an HTTP or process adapter."""

    def complete(self, prompt: str, model_name: str, timeout_seconds: float) -> str:
        """Return the raw model response for one prompt."""
        ...


def _require_loopback_endpoint(endpoint: str) -> None:
    """Prevent the local provider from silently becoming an external client."""
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError(
            "LocalAIProvider endpoints must use localhost, 127.0.0.1, or ::1."
        )


@dataclass(frozen=True, slots=True)
class HttpLocalModelTransport:
    """Speak the small JSON-over-HTTP contract used by a local model runtime.

    Request body:
    ``{"model": "...", "prompt": "...", "stream": false}``

    The response may be a JSON object with ``response``, ``text``, ``output``,
    ``content``, or ``message.content``; it may also be a JSON string or raw
    JSON text. This keeps the runtime-specific envelope in this adapter.
    """

    endpoint: str

    def __post_init__(self) -> None:
        _require_loopback_endpoint(self.endpoint)

    def complete(self, prompt: str, model_name: str, timeout_seconds: float) -> str:
        body = json.dumps(
            {"model": model_name, "prompt": prompt, "stream": False}
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise LocalProviderConnectionError(
                f"Could not reach local model endpoint {self.endpoint}: {error}"
            ) from error
        return _extract_runtime_text(raw_body)


@dataclass(frozen=True, slots=True)
class ProcessLocalModelTransport:
    """Run a local model gateway process with no shell or unrestricted command."""

    command: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.command or not self.command[0]:
            raise ValueError("A local model process command cannot be empty.")

    @classmethod
    def from_command(cls, command: str) -> "ProcessLocalModelTransport":
        """Parse a command using shell-like quoting without invoking a shell."""
        parsed = tuple(shlex.split(command))
        return cls(parsed)

    def complete(self, prompt: str, model_name: str, timeout_seconds: float) -> str:
        del model_name
        try:
            completed = subprocess.run(
                self.command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise LocalProviderConnectionError(
                f"Local model process could not complete: {error}"
            ) from error
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "process returned a non-zero exit code"
            raise LocalProviderConnectionError(
                f"Local model process failed ({completed.returncode}): {detail}"
            )
        return completed.stdout


class LocalAIProvider:
    """Convert structured JARVIS requests into prompts for a local model.

    The model is required to return JSON matching the schema in each prompt.
    Parsing is strict enough to prevent malformed model output from becoming a
    false plan or code change, while accepting a single markdown JSON fence
    commonly emitted by local models.
    """

    def __init__(
        self,
        transport: LocalModelTransport,
        model_name: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not model_name.strip():
            raise ValueError("A local model name cannot be empty.")
        if timeout_seconds <= 0:
            raise ValueError("Local model timeout must be positive.")
        self.transport = transport
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.name = f"local:{model_name}"

    @classmethod
    def from_settings(cls, settings: Settings) -> "LocalAIProvider":
        """Build the configured endpoint or process adapter."""
        if settings.local_provider_mode == "process":
            if not settings.local_process_command:
                raise ValueError(
                    "JARVIS_LOCAL_PROCESS_COMMAND is required in process mode."
                )
            transport: LocalModelTransport = ProcessLocalModelTransport.from_command(
                settings.local_process_command
            )
        else:
            transport = HttpLocalModelTransport(settings.local_endpoint)
        return cls(
            transport,
            settings.local_model_name,
            settings.local_provider_timeout_seconds,
        )

    def create_plan(self, goal: str, memory_context: tuple[str, ...]) -> Plan:
        prompt = _plan_prompt(goal, memory_context)
        payload = self._request_json(prompt)
        try:
            steps = tuple(
                PlanStep(
                    identifier=str(item["identifier"]),
                    objective=str(item["objective"]),
                    tool_name=str(item["tool_name"]),
                    argument=str(item.get("argument", "")),
                    verification=str(item.get("verification", "")),
                    max_retries=int(item.get("max_retries", 0)),
                )
                for item in payload["steps"]
            )
        except (KeyError, TypeError, ValueError) as error:
            raise LocalProviderResponseError(
                "Local model plan JSON must contain a valid 'steps' array."
            ) from error
        return Plan(
            goal=str(payload.get("goal", goal)),
            steps=steps,
            provider=self.name,
        )

    def generate_code(self, request: CodeGenerationRequest) -> tuple[CodeChange, ...]:
        payload = self._request_json(_code_prompt(request))
        try:
            return tuple(
                CodeChange(path=str(item["path"]), content=str(item["content"]))
                for item in payload["changes"]
            )
        except (KeyError, TypeError, ValueError) as error:
            raise LocalProviderResponseError(
                "Local model code JSON must contain a valid 'changes' array."
            ) from error

    def propose_improvement(
        self, report: ExecutionReport, memory_context: tuple[str, ...]
    ) -> ImprovementProposal:
        payload = self._request_json(_improvement_prompt(report, memory_context))
        try:
            changes = tuple(
                CodeChange(path=str(item["path"]), content=str(item["content"]))
                for item in payload["changes"]
            )
            return ImprovementProposal(
                title=str(payload["title"]),
                rationale=str(payload["rationale"]),
                changes=changes,
                provider=self.name,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise LocalProviderResponseError(
                "Local model improvement JSON must contain title, rationale, and changes."
            ) from error

    def _request_json(self, prompt: str) -> dict[str, Any]:
        try:
            raw_response = self.transport.complete(
                prompt,
                self.model_name,
                self.timeout_seconds,
            )
        except LocalProviderError:
            raise
        except Exception as error:
            raise LocalProviderConnectionError(
                f"Local model transport failed: {error}"
            ) from error
        try:
            decoded = json.loads(_strip_json_fence(raw_response))
        except (json.JSONDecodeError, TypeError) as error:
            raise LocalProviderResponseError(
                "Local model returned non-JSON output; no action was taken."
            ) from error
        if not isinstance(decoded, dict):
            raise LocalProviderResponseError(
                "Local model response must be a JSON object; no action was taken."
            )
        return decoded


def _extract_runtime_text(raw_body: str) -> str:
    """Extract model text from common local-runtime response envelopes."""
    try:
        decoded = json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body
    if isinstance(decoded, str):
        return decoded
    if not isinstance(decoded, dict):
        return raw_body
    for key in ("response", "text", "output", "content"):
        value = decoded.get(key)
        if isinstance(value, str):
            return value
    message = decoded.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return json.dumps(decoded)


def _strip_json_fence(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _plan_prompt(goal: str, memory_context: tuple[str, ...]) -> str:
    memory = "\n".join(f"- {item}" for item in memory_context) or "(none)"
    return f"""You are the planning component of JARVIS.
Create a safe, finite plan for this goal:
{goal}

Relevant local memory:
{memory}

Return JSON only with this shape:
{{"goal":"exact goal","steps":[{{"identifier":"step-1","objective":"...",
"tool_name":"registered tool name","argument":"...", "verification":"...",
"max_retries":0}}]}}
Do not invent tools. Use only tools available to the executor."""


def _code_prompt(request: CodeGenerationRequest) -> str:
    existing = "\n\n".join(
        f"FILE {path}:\n{content}" for path, content in request.existing_files.items()
    ) or "(files do not exist yet)"
    allowed = ", ".join(request.allowed_files)
    return f"""You are the restricted code component of JARVIS.
Goal: {request.goal}
Allowed Python files only: {allowed}
Existing files:
{existing}

Return JSON only:
{{"changes":[{{"path":"allowed.py","content":"complete Python file text"}}]}}
Never include files outside the allow-list. Do not use shell commands."""


def _improvement_prompt(
    report: ExecutionReport, memory_context: tuple[str, ...]
) -> str:
    return f"""You are the self-improvement proposal component of JARVIS.
Execution goal: {report.goal}
Execution success: {report.success}
Failure: {report.failure or "(none)"}
Memory context: {memory_context}

Return JSON only:
{{"title":"...", "rationale":"...", "changes":[
{{"path":"allowed.py","content":"complete Python file text"}}
]}}
This is a proposal only. Do not claim that changes were applied."""


def build_local_brain(settings: Settings) -> "ProviderBrain":
    """Create the Brain adapter without changing JARVIS Core."""
    from .brain import ProviderBrain

    return ProviderBrain(LocalAIProvider.from_settings(settings))
