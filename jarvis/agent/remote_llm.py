"""Remote LLM provider for JARVIS.

Implements the Brain protocol using an external LLM API (OpenAI-compatible or
Anthropic).  The transport is a pluggable Protocol so tests can run without any
real API key.

Environment variables consumed (NOT stored in Settings — the key is a secret):
    JARVIS_LLM_API_KEY   Required when llm_enabled=True.  Never log or expose.

Settings fields (in jarvis.config.Settings) drive the rest:
    llm_enabled  bool  — activates this brain
    llm_provider str   — "openai" | "anthropic" | "groq" | "openrouter" | custom base-URL
    llm_model    str   — model name forwarded to the provider verbatim

Safety constraints (not relaxed):
    - Tool calls go through the existing ToolRegistry.
    - No shell commands, no filesystem writes outside the sandbox.
    - No secrets reach the LLM prompt.
    - The LLM cannot self-grant permissions.
"""

from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .brain import BrainError, ProviderBrain
from .models import (
    CodeChange,
    CodeGenerationRequest,
    ExecutionReport,
    ImprovementProposal,
    Plan,
    PlanStep,
)

# ── Errors ────────────────────────────────────────────────────────────────────

class RemoteLLMError(BrainError):
    """Base error for remote LLM failures."""


class RemoteLLMConnectionError(RemoteLLMError):
    """Could not reach or authenticate to the LLM API."""


class RemoteLLMResponseError(RemoteLLMError):
    """LLM returned output that could not be parsed into the expected structure."""


class RemoteLLMConfigError(RemoteLLMError):
    """Required credentials or configuration are absent."""


# ── Transport protocol ────────────────────────────────────────────────────────

class LLMTransport(Protocol):
    """Pluggable transport — swap in MockLLMTransport for tests."""

    def chat_complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        api_key: str,
        timeout_seconds: float,
    ) -> str:
        """Send a chat-completion request and return the assistant text."""
        ...


# ── Concrete transports ───────────────────────────────────────────────────────

# Maps provider aliases to their OpenAI-compatible base URLs.
_PROVIDER_URLS: dict[str, str] = {
    "openai": "https://api.openai.com",
    "groq": "https://api.groq.com/openai",
    "openrouter": "https://openrouter.ai/api",
}


@dataclass(frozen=True, slots=True)
class OpenAICompatibleTransport:
    """HTTP transport for OpenAI chat completions API format.

    Works with OpenAI, Groq, OpenRouter, and any other provider that speaks
    the /v1/chat/completions endpoint.  Pass ``base_url`` directly to target
    a custom provider (e.g. a self-hosted inference server).
    """

    base_url: str

    def chat_complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        api_key: str,
        timeout_seconds: float,
    ) -> str:
        endpoint = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        body = json.dumps(
            {
                "model": model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 2048,
            }
        ).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                # A recognised API-client User-Agent is required.  Without it
                # Cloudflare (which fronts Groq and several other providers)
                # returns 403 error-code 1010 before the request ever reaches
                # the provider's own servers.  Python's default urllib UA
                # ("Python-urllib/3.x") triggers that block.
                "User-Agent": "groq-python/0.11.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as error:
            # Read the response body so diagnostics are meaningful.
            # HTTPError.read() can only be called once and may raise; guard it.
            try:
                error_body = error.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = ""
            detail = f" — {error_body[:300]}" if error_body.strip() else ""
            raise RemoteLLMConnectionError(
                f"LLM API returned HTTP {error.code}: {error.reason}{detail}"
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise RemoteLLMConnectionError(
                f"Could not reach LLM API at {endpoint}: {error}"
            ) from error
        try:
            decoded = json.loads(raw)
            return str(decoded["choices"][0]["message"]["content"])
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise RemoteLLMResponseError(
                f"LLM API returned unexpected response shape: {error}"
            ) from error


@dataclass(frozen=True, slots=True)
class AnthropicTransport:
    """HTTP transport for the Anthropic messages API."""

    base_url: str = "https://api.anthropic.com"
    api_version: str = "2023-06-01"

    def chat_complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        api_key: str,
        timeout_seconds: float,
    ) -> str:
        system_parts: list[str] = []
        chat_messages: list[dict[str, str]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_parts.append(msg["content"])
            else:
                chat_messages.append(msg)

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": 2048,
            "messages": chat_messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        endpoint = f"{self.base_url.rstrip('/')}/v1/messages"
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": self.api_version,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as error:
            raise RemoteLLMConnectionError(
                f"Anthropic API returned HTTP {error.code}: {error.reason}"
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise RemoteLLMConnectionError(
                f"Could not reach Anthropic API: {error}"
            ) from error
        try:
            decoded = json.loads(raw)
            return str(decoded["content"][0]["text"])
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise RemoteLLMResponseError(
                f"Anthropic API returned unexpected response shape: {error}"
            ) from error


class MockLLMTransport:
    """In-process mock transport for tests — no real API key or network required.

    Responses are consumed FIFO from the list passed at construction.
    Call ``calls`` to inspect what messages were sent.
    """

    def __init__(self, responses: list[str] | None = None) -> None:
        self._queue: deque[str] = deque(responses or [])
        self._calls: list[list[dict[str, str]]] = []

    def chat_complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        api_key: str,
        timeout_seconds: float,
    ) -> str:
        self._calls.append(list(messages))
        if not self._queue:
            raise RemoteLLMConnectionError("MockLLMTransport has no more queued responses.")
        return self._queue.popleft()

    @property
    def calls(self) -> list[list[dict[str, str]]]:
        """All message lists sent to this transport, in order."""
        return list(self._calls)

    def remaining(self) -> int:
        """How many queued responses remain."""
        return len(self._queue)


# ── Prompts ───────────────────────────────────────────────────────────────────

_AVAILABLE_TOOLS = """
Available tools (use ONLY these exact tool_name values):
  echo      Return text to the user. argument = text to show (required).
  time      Return the current UTC time. argument = "" (leave empty).
  remember  Store a fact persistently. argument = the fact to store (required).
  recall    Search stored memories. argument = search query (use "" to list all).
"""

_PLAN_SYSTEM = """\
You are the planning brain of JARVIS, a safe local-first autonomous assistant.
Your only job in this message is to produce a structured execution plan as JSON.

{tools}

Strict rules:
1. The "goal" field MUST be EXACTLY the goal string you are given — no paraphrasing,
   no additions, no changes.  Copy it verbatim.
2. Use ONLY the tool names listed above.  Never invent new tools.
3. Step identifiers must be unique, non-empty, kebab-case (e.g. "step-1", "store-name").
4. max_retries must be 0 or a positive integer.
5. If the user wants to store a fact, use the "remember" tool.
6. If the user asks about past facts, start with a "recall" step.
7. Use "echo" to communicate information or results to the user.
8. Keep plans short (1–4 steps).  Only include steps that directly serve the goal.
9. Do NOT invent tool names, do NOT include shell commands or file operations.
10. Return ONLY valid JSON — no prose, no markdown fences, no explanations.

Relevant stored memories (use these to answer recall/name questions):
{memory}

Required JSON format:
{{"goal":"<exact goal string>","steps":[{{"identifier":"step-1","objective":"<why>",\
"tool_name":"<tool>","argument":"<arg>","verification":"<pass condition>","max_retries":0}}]}}
"""

_CODE_SYSTEM = """\
You are the restricted code generator of JARVIS.
Goal: {goal}
Allowed Python files only: {allowed}
Existing files:
{existing}

Return ONLY valid JSON:
{{"changes":[{{"path":"allowed.py","content":"complete Python file text"}}]}}
Never include files outside the allow-list. No shell commands."""

_IMPROVEMENT_SYSTEM = """\
You are the self-improvement proposal component of JARVIS.
Execution goal: {goal}
Execution success: {success}
Failure: {failure}
Memory context: {memory}

Return ONLY valid JSON:
{{"title":"...","rationale":"...","changes":[{{"path":"allowed.py","content":"..."}}]}}
This is a proposal only — do not claim changes were applied."""


# ── Brain ─────────────────────────────────────────────────────────────────────

_HISTORY_LIMIT = 6  # max messages kept (3 user/assistant pairs)


class RemoteLLMBrain:
    """JARVIS Brain backed by a remote LLM API.

    Implements the Brain protocol.  All tool calls still go through the
    existing ToolRegistry → safe sandbox boundary — the LLM only generates
    plans; it never executes anything directly.

    The provider name is ``llm:<provider>:<model>`` so the frontend can
    distinguish REAL LLM mode from DEMO and LOCAL LLM modes.

    Conversation history (rolling window) is included in each plan request so
    the LLM understands multi-turn context ("What is my name?" after
    "Remember my name is San").
    """

    def __init__(
        self,
        transport: LLMTransport,
        model: str,
        provider_alias: str,
        api_key: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not model.strip():
            raise ValueError("LLM model name cannot be empty.")
        if not api_key.strip():
            raise RemoteLLMConfigError(
                "JARVIS_LLM_API_KEY is required when LLM mode is enabled. "
                "Set it as a Replit secret."
            )
        self._transport = transport
        self._model = model
        self._provider_alias = provider_alias
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._history: deque[dict[str, str]] = deque(maxlen=_HISTORY_LIMIT)

    @property
    def provider_name(self) -> str:
        return f"llm:{self._provider_alias}:{self._model}"

    def create_plan(self, goal: str, memory_context: tuple[str, ...]) -> Plan:
        """Ask the LLM to produce a structured plan for the goal."""
        memory_text = (
            "\n".join(f"- {m}" for m in memory_context) or "(no relevant memories)"
        )
        system = _PLAN_SYSTEM.format(
            tools=_AVAILABLE_TOOLS,
            memory=memory_text,
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(self._history)
        messages.append({"role": "user", "content": goal})

        raw = self._call(messages)

        # Add to history for multi-turn context
        self._history.append({"role": "user", "content": goal})
        self._history.append({"role": "assistant", "content": raw})

        return self._parse_plan(raw, goal)

    def generate_code(self, request: CodeGenerationRequest) -> tuple[CodeChange, ...]:
        existing = (
            "\n\n".join(
                f"FILE {p}:\n{c}" for p, c in request.existing_files.items()
            )
            or "(files do not exist yet)"
        )
        allowed = ", ".join(request.allowed_files)
        system = _CODE_SYSTEM.format(
            goal=request.goal,
            allowed=allowed,
            existing=existing,
        )
        raw = self._call([{"role": "system", "content": system}])
        payload = self._parse_json(raw)
        try:
            return tuple(
                CodeChange(path=str(item["path"]), content=str(item["content"]))
                for item in payload["changes"]
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RemoteLLMResponseError(
                "LLM code JSON must contain a valid 'changes' array."
            ) from error

    def propose_improvement(
        self, report: ExecutionReport, memory_context: tuple[str, ...]
    ) -> ImprovementProposal:
        system = _IMPROVEMENT_SYSTEM.format(
            goal=report.goal,
            success=report.success,
            failure=report.failure or "(none)",
            memory=memory_context,
        )
        raw = self._call([{"role": "system", "content": system}])
        payload = self._parse_json(raw)
        try:
            changes = tuple(
                CodeChange(path=str(item["path"]), content=str(item["content"]))
                for item in payload["changes"]
            )
            return ImprovementProposal(
                title=str(payload["title"]),
                rationale=str(payload["rationale"]),
                changes=changes,
                provider=self.provider_name,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RemoteLLMResponseError(
                "LLM improvement JSON must contain title, rationale, and changes."
            ) from error

    # ── Private helpers ────────────────────────────────────────────────────

    def _call(self, messages: list[dict[str, str]]) -> str:
        try:
            return self._transport.chat_complete(
                messages, self._model, self._api_key, self._timeout
            )
        except RemoteLLMError:
            raise
        except Exception as error:
            raise RemoteLLMConnectionError(
                f"LLM transport raised an unexpected error: {error}"
            ) from error

    def _parse_json(self, raw: str) -> dict[str, Any]:
        stripped = raw.strip()
        # Strip markdown fences if present
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(lines[1:-1]).strip()
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise RemoteLLMResponseError(
                f"LLM returned non-JSON output: {error}"
            ) from error
        if not isinstance(decoded, dict):
            raise RemoteLLMResponseError(
                "LLM response must be a JSON object."
            )
        return decoded

    def _parse_plan(self, raw: str, goal: str) -> Plan:
        payload = self._parse_json(raw)
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
            raise RemoteLLMResponseError(
                "LLM plan JSON must contain a valid 'steps' array with "
                "identifier, objective, and tool_name fields."
            ) from error
        # Force goal to match exactly — the Planner validates plan.goal == goal.
        # The LLM might paraphrase; we trust ourselves over the LLM output here.
        return Plan(goal=goal, steps=steps, provider=self.provider_name)


# ── Factory ───────────────────────────────────────────────────────────────────

def build_remote_llm_brain(settings: "Settings") -> RemoteLLMBrain:  # type: ignore[name-defined]
    """Construct a RemoteLLMBrain from Settings + JARVIS_LLM_API_KEY secret.

    Fails loudly with RemoteLLMConfigError if the API key is absent rather
    than silently falling back to another provider.
    """
    from ..config import Settings as _Settings  # local import to avoid circular

    api_key = os.environ.get("JARVIS_LLM_API_KEY", "").strip()
    if not api_key:
        raise RemoteLLMConfigError(
            "JARVIS_LLM_API_KEY is required when JARVIS_LLM_ENABLED=true. "
            "Add it as a Replit secret."
        )

    provider = settings.llm_provider.lower().strip()
    model = settings.llm_model.strip()
    timeout = settings.local_provider_timeout_seconds  # reuse existing timeout setting

    if provider == "anthropic":
        transport: LLMTransport = AnthropicTransport()
    else:
        # Resolve alias or treat as a raw base URL
        base_url = _PROVIDER_URLS.get(provider, provider)
        transport = OpenAICompatibleTransport(base_url=base_url)

    return RemoteLLMBrain(
        transport=transport,
        model=model,
        provider_alias=provider,
        api_key=api_key,
        timeout_seconds=timeout,
    )
