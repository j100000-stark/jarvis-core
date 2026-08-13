"""Extended JARVIS tool set for V1.

All tools are safe, local-first, and operate within the explicit capability
boundary defined by ToolContext.  No tool may:
  - execute arbitrary shell commands
  - access files outside the workspace sandbox
  - call external APIs unless the relevant setting is enabled
  - fabricate results — if a capability is unavailable it says so clearly

New tools in this module:
  system_status   — runtime status without a subprocess call
  network_status  — probe known public hosts via TCP socket
  calculate       — safe AST-based math evaluator
  analyze_text    — text statistics and keyword extraction
  web_research    — safe HTTP fetch / DuckDuckGo instant-answer (gated)
  security_status — JARVIS safety boundary summary
  report          — format a structured plain-text report
"""

from __future__ import annotations

import ast
import json
import operator as op
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser

from ..agent.models import PlanStep, ToolResult
from .registry import Tool, ToolContext, ToolRegistry


# ---------------------------------------------------------------------------
# SystemStatusTool
# ---------------------------------------------------------------------------

class SystemStatusTool:
    """Return current JARVIS runtime facts without spawning a subprocess."""

    name = "system_status"
    description = "Show JARVIS runtime status: time, memories, settings summary."

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        del argument
        now = datetime.now(UTC).isoformat(timespec="seconds")
        s = context.settings
        lines = [
            f"Time (UTC): {now}",
            f"JARVIS {s.name} {s.version}",
            f"Memories stored: {context.memory.count()}",
            f"  long-term: {context.memory.count(tier='long_term')}",
            f"  episodic:  {context.memory.count(tier='episodic')}",
            f"  system:    {context.memory.count(tier='system')}",
            f"Demo mode: {'yes' if s.demo_mode else 'no'}",
            f"LLM mode: {'yes' if s.llm_enabled else 'no'}",
            f"Web research: {'enabled' if s.web_research_enabled else 'disabled'}",
            f"Sandbox timeout: {s.sandbox_timeout_seconds}s",
        ]
        return ToolResult(ok=True, output="\n".join(lines))

    def verify(self, result: ToolResult, step: PlanStep) -> bool:
        del step
        return result.ok and "Time (UTC):" in (result.output or "")


# ---------------------------------------------------------------------------
# NetworkStatusTool
# ---------------------------------------------------------------------------

class NetworkStatusTool:
    """Check network connectivity by probing known public DNS hosts."""

    name = "network_status"
    description = "Probe public network hosts to determine connectivity status."

    _PROBE_HOSTS = [("1.1.1.1", 53), ("8.8.8.8", 53)]

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        del argument
        timeout = context.settings.network_probe_timeout_seconds
        reachable: list[str] = []
        unreachable: list[str] = []
        for host, port in self._PROBE_HOSTS:
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    reachable.append(host)
            except OSError:
                unreachable.append(host)

        if reachable:
            status = "online"
        elif unreachable:
            status = "offline"
        else:
            status = "unknown"

        lines = [f"Network: {status}"]
        lines += [f"  reachable:   {h}" for h in reachable]
        lines += [f"  unreachable: {h}" for h in unreachable]
        return ToolResult(ok=True, output="\n".join(lines))

    def verify(self, result: ToolResult, step: PlanStep) -> bool:
        del step
        return result.ok and "Network:" in (result.output or "")


# ---------------------------------------------------------------------------
# CalculateTool — AST-safe math evaluator
# ---------------------------------------------------------------------------

_BINOPS: dict[type, object] = {
    ast.Add:  op.add,
    ast.Sub:  op.sub,
    ast.Mult: op.mul,
    ast.Div:  op.truediv,
    ast.Mod:  op.mod,
    ast.Pow:  op.pow,
    ast.FloorDiv: op.floordiv,
}
_UNARYOPS: dict[type, object] = {
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}


def _safe_eval(node: ast.expr) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Unsupported literal: {node.value!r}")
    if isinstance(node, ast.BinOp):
        fn = _BINOPS.get(type(node.op))
        if fn is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return fn(left, right)  # type: ignore[operator]
    if isinstance(node, ast.UnaryOp):
        fn = _UNARYOPS.get(type(node.op))
        if fn is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return fn(_safe_eval(node.operand))  # type: ignore[operator]
    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


class CalculateTool:
    """Evaluate a safe mathematical expression using AST parsing (no eval)."""

    name = "calculate"
    description = "Evaluate a math expression safely: calculate 2 + 2 * 10"

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        del context
        expr = argument.strip()
        if not expr:
            return ToolResult(ok=False, error="Usage: calculate <math expression>")
        try:
            tree = ast.parse(expr, mode="eval")
            result = _safe_eval(tree.body)
            # Return integer representation when lossless
            if isinstance(result, float) and result.is_integer():
                formatted = str(int(result))
            else:
                formatted = f"{result:.10g}"
            return ToolResult(ok=True, output=f"{expr} = {formatted}")
        except (ValueError, ZeroDivisionError, SyntaxError, RecursionError) as exc:
            return ToolResult(ok=False, error=f"Cannot evaluate '{expr}': {exc}")

    def verify(self, result: ToolResult, step: PlanStep) -> bool:
        del step
        return result.ok and "=" in (result.output or "")


# ---------------------------------------------------------------------------
# AnalyzeTextTool
# ---------------------------------------------------------------------------

class AnalyzeTextTool:
    """Compute basic text statistics and extract key terms."""

    name = "analyze_text"
    description = "Analyze text: word count, sentences, top words. analyze_text <text>"

    _STOP_WORDS = frozenset(
        "a an the is are was were be been being have has had do does did "
        "will would shall should may might must can could of in on at to "
        "for by with from this that it its i me my we our you your he she "
        "they them their what which who how when where why and or but not "
        "also if then as so just very all any some no more one two".split()
    )

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        del context
        text = argument.strip()
        if not text:
            return ToolResult(ok=False, error="Usage: analyze_text <text to analyze>")

        words = text.split()
        word_count = len(words)
        char_count = len(text)
        sentence_count = max(
            1,
            text.count(".") + text.count("!") + text.count("?"),
        )
        avg_words_per_sentence = word_count / sentence_count

        # Top non-stop-word tokens
        freq: dict[str, int] = {}
        for w in words:
            token = w.strip(".,!?;:\"'()[]{}").lower()
            if token and token not in self._STOP_WORDS and len(token) > 2:
                freq[token] = freq.get(token, 0) + 1
        top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5]
        top_words = ", ".join(f"{w}({n})" for w, n in top) if top else "—"

        lines = [
            f"Characters: {char_count}",
            f"Words: {word_count}",
            f"Sentences (approx): {sentence_count}",
            f"Avg words/sentence: {avg_words_per_sentence:.1f}",
            f"Top keywords: {top_words}",
        ]
        return ToolResult(ok=True, output="\n".join(lines))

    def verify(self, result: ToolResult, step: PlanStep) -> bool:
        del step
        return result.ok and "Words:" in (result.output or "")


# ---------------------------------------------------------------------------
# WebResearchTool
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text extractor for urllib fetches."""

    def __init__(self) -> None:
        super().__init__()
        self._skip = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style", "nav", "footer", "header", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer", "header", "noscript"}:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def text(self, max_chars: int = 1500) -> str:
        return " ".join(self._parts)[:max_chars]


def _fetch_url(url: str, timeout: float = 8.0) -> str:
    """Fetch a URL and return plain-text excerpt.  Raises on failure."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "JARVIS/1.0 (research tool; read-only)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get_content_type() or ""
        raw = resp.read(65536).decode("utf-8", errors="replace")

    if "html" in content_type:
        parser = _TextExtractor()
        parser.feed(raw)
        return parser.text()
    return raw[:1500]


def _duckduckgo_instant(query: str, timeout: float = 8.0) -> str:
    """Query DuckDuckGo Instant Answer API (no key required).

    Returns a plain-text answer or an empty string if nothing useful was found.
    """
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
    })
    url = f"https://api.duckduckgo.com/?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "JARVIS/1.0 (research tool; read-only)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read(131072))

    parts: list[str] = []
    if data.get("AbstractText"):
        parts.append(data["AbstractText"])
        if data.get("AbstractURL"):
            parts.append(f"Source: {data['AbstractURL']}")
    if data.get("Answer"):
        parts.append(f"Answer: {data['Answer']}")
    for topic in (data.get("RelatedTopics") or [])[:3]:
        if isinstance(topic, dict) and topic.get("Text"):
            parts.append(f"• {topic['Text'][:200]}")

    return "\n".join(parts)


class WebResearchTool:
    """Safe web research via urllib.

    If the argument starts with http:// or https://, the URL is fetched
    directly and a text excerpt is returned.  Otherwise the DuckDuckGo
    Instant Answer API is queried (no API key required).

    This capability is gated by settings.web_research_enabled.  If it is
    disabled, JARVIS reports this honestly instead of fabricating a result.

    JARVIS will NOT:
      - bypass authentication, paywalls, or CAPTCHAs
      - visit a site without actually fetching it
      - fabricate search results
    """

    name = "web_research"
    description = (
        "Research a URL or topic online. "
        "Provide a URL to fetch or a plain query: web_research climate change"
    )

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        if not context.settings.web_research_enabled:
            return ToolResult(
                ok=False,
                error=(
                    "Web research is not currently enabled. "
                    "Set JARVIS_WEB_RESEARCH_ENABLED=true to enable safe HTTP access."
                ),
            )
        query = argument.strip()
        if not query:
            return ToolResult(
                ok=False,
                error="Usage: web_research <URL or search query>",
            )

        try:
            if query.startswith(("http://", "https://")):
                text = _fetch_url(query)
                if not text.strip():
                    return ToolResult(ok=False, error=f"No readable content found at {query}")
                return ToolResult(
                    ok=True,
                    output=f"[Fetched: {query}]\n{text}",
                )
            else:
                text = _duckduckgo_instant(query)
                if not text.strip():
                    return ToolResult(
                        ok=True,
                        output=(
                            f"No instant-answer result found for '{query}'. "
                            "Try a more specific query or provide a URL."
                        ),
                    )
                return ToolResult(
                    ok=True,
                    output=f"[DuckDuckGo: {query}]\n{text}",
                )
        except urllib.error.HTTPError as exc:
            return ToolResult(
                ok=False,
                error=f"HTTP error {exc.code} fetching '{query}': {exc.reason}",
            )
        except urllib.error.URLError as exc:
            return ToolResult(
                ok=False,
                error=f"Network error fetching '{query}': {exc.reason}",
            )
        except TimeoutError:
            return ToolResult(
                ok=False,
                error=f"Request timed out for '{query}'.",
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                ok=False,
                error=f"Web research failed for '{query}': {exc}",
            )

    def verify(self, result: ToolResult, step: PlanStep) -> bool:
        del step
        return result.ok


# ---------------------------------------------------------------------------
# SecurityStatusTool
# ---------------------------------------------------------------------------

class SecurityStatusTool:
    """Report JARVIS safety boundaries — what it will and will not do."""

    name = "security_status"
    description = "Summarise JARVIS active safety boundaries and current security posture."

    _WILL_NOT = [
        "execute arbitrary shell commands",
        "access files outside the declared workspace",
        "obtain unauthorised access to third-party systems",
        "bypass authentication, paywalls, or access controls",
        "silently install software or grant itself new privileges",
        "fabricate tool results or claim an action was taken when it was not",
        "expose secrets, tokens, or credentials in output",
        "perform destructive actions without explicit approval",
    ]

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        del argument
        s = context.settings
        lines = [
            "JARVIS V1 — Security status",
            "",
            "Active safety boundaries:",
            f"  Sandbox enabled: yes (timeout {s.sandbox_timeout_seconds}s)",
            f"  Web research gated: {'enabled' if s.web_research_enabled else 'disabled'}",
            f"  External API access: {'limited (web research only)' if s.web_research_enabled else 'none'}",
            f"  Demo mode: {'yes (scripted, no real AI)' if s.demo_mode else 'no'}",
            "",
            "JARVIS will NOT:",
        ]
        lines += [f"  ✗ {item}" for item in self._WILL_NOT]
        lines += [
            "",
            "Privileged actions require explicit capability permission and approval.",
        ]
        return ToolResult(ok=True, output="\n".join(lines))

    def verify(self, result: ToolResult, step: PlanStep) -> bool:
        del step
        return result.ok and "JARVIS V1" in (result.output or "")


# ---------------------------------------------------------------------------
# ReportTool
# ---------------------------------------------------------------------------

class ReportTool:
    """Format a block of text as a timestamped structured report."""

    name = "report"
    description = "Format text as a structured JARVIS report: report <content>"

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        del context
        content = argument.strip()
        if not content:
            return ToolResult(ok=False, error="Usage: report <content to format>")
        now = datetime.now(UTC).isoformat(timespec="seconds")
        output = (
            f"━━━ JARVIS REPORT ━━━\n"
            f"Generated: {now}\n"
            f"{'─' * 30}\n"
            f"{content}\n"
            f"{'─' * 30}\n"
            f"━━━ END REPORT ━━━"
        )
        return ToolResult(ok=True, output=output)

    def verify(self, result: ToolResult, step: PlanStep) -> bool:
        del step
        return result.ok and "JARVIS REPORT" in (result.output or "")


# ---------------------------------------------------------------------------
# Registry factory
# ---------------------------------------------------------------------------

def build_extended_registry_additions() -> list[Tool]:
    """Return all V1 extended tools ready to register."""
    return [
        SystemStatusTool(),
        NetworkStatusTool(),
        CalculateTool(),
        AnalyzeTextTool(),
        WebResearchTool(),
        SecurityStatusTool(),
        ReportTool(),
    ]
