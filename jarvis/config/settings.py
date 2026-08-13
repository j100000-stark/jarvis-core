"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable runtime configuration."""

    name: str = "JARVIS"
    version: str = "v1.0.0"
    data_dir: Path = Path("data")
    memory_file: Path = Path("data/memory.json")
    max_memory_items: int = 500
    sandbox_timeout_seconds: float = 5.0
    autonomous_max_retries: int = 3
    local_provider_enabled: bool = False
    local_provider_mode: str = "http"
    local_endpoint: str = "http://localhost:11434"
    local_process_command: str | None = None
    local_model_name: str = "local"
    local_provider_timeout_seconds: float = 30.0
    demo_mode: bool = False
    # Remote LLM provider (JARVIS_LLM_ENABLED=true activates this brain)
    # JARVIS_LLM_API_KEY is consumed directly from the environment by
    # jarvis.agent.remote_llm — it is intentionally not stored here.
    llm_enabled: bool = False
    llm_provider: str = "openai"   # "openai" | "anthropic" | "groq" | "openrouter" | base-URL
    llm_model: str = "gpt-4o-mini"
    # Web research: safe HTTP fetch capability.
    # Disabled by default; enable with JARVIS_WEB_RESEARCH_ENABLED=true.
    web_research_enabled: bool = True
    # Network probe timeout for the network_status tool
    network_probe_timeout_seconds: float = 3.0

    @classmethod
    def from_environment(cls, memory_file: str | None = None) -> "Settings":
        """Build Settings from JARVIS_* environment variables.

        Precedence: environment variable > runtime_config.json overlay > default.
        The overlay (data/runtime_config.json) is the authoritative persistent
        source for configuration repairs — apply_to_environ() fills only keys
        the operator has not explicitly set in the environment.
        """
        from .config_store import ConfigStore
        ConfigStore().apply_to_environ()

        data_dir_str = os.environ.get("JARVIS_DATA_DIR", "data")
        data_dir = Path(data_dir_str)
        default_memory = data_dir / "memory.json"
        mem_path = Path(memory_file) if memory_file else default_memory

        return cls(
            name=os.environ.get("JARVIS_NAME", "JARVIS"),
            version=os.environ.get("JARVIS_VERSION", "v1.0.0"),
            data_dir=data_dir,
            memory_file=mem_path,
            max_memory_items=_positive_int(os.environ.get("JARVIS_MAX_MEMORY"), 500),
            sandbox_timeout_seconds=_positive_float(
                os.environ.get("JARVIS_SANDBOX_TIMEOUT"), 5.0
            ),
            autonomous_max_retries=_positive_int(
                os.environ.get("JARVIS_MAX_RETRIES"), 3
            ),
            local_provider_enabled=_boolean(
                os.environ.get("JARVIS_LOCAL_PROVIDER_ENABLED"), False
            ),
            local_provider_mode=os.environ.get("JARVIS_LOCAL_PROVIDER_MODE", "http"),
            local_endpoint=os.environ.get(
                "JARVIS_LOCAL_ENDPOINT", "http://localhost:11434"
            ),
            local_process_command=os.environ.get("JARVIS_LOCAL_PROCESS_COMMAND"),
            local_model_name=os.environ.get("JARVIS_LOCAL_MODEL_NAME", "local"),
            local_provider_timeout_seconds=_positive_float(
                os.environ.get("JARVIS_LOCAL_PROVIDER_TIMEOUT"), 30.0
            ),
            demo_mode=_boolean(os.environ.get("JARVIS_DEMO_MODE"), False),
            llm_enabled=_boolean(os.environ.get("JARVIS_LLM_ENABLED"), False),
            llm_provider=os.environ.get("JARVIS_LLM_PROVIDER", "openai"),
            llm_model=os.environ.get("JARVIS_LLM_MODEL", "gpt-4o-mini"),
            web_research_enabled=_boolean(
                os.environ.get("JARVIS_WEB_RESEARCH_ENABLED"), True
            ),
            network_probe_timeout_seconds=_positive_float(
                os.environ.get("JARVIS_NETWORK_PROBE_TIMEOUT"), 3.0
            ),
        )


def _positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except ValueError:
        return default


def _positive_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
        return parsed if parsed > 0 else default
    except ValueError:
        return default


def _boolean(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
