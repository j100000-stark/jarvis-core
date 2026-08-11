"""Autonomous goal execution components.

Exports are loaded lazily because the tool registry and agent executor depend
on one another's shared models.
"""

from importlib import import_module

__all__ = [
    "AIProvider",
    "AgentExecutor",
    "Brain",
    "BrainError",
    "BrainUnavailableError",
    "build_local_brain",
    "build_remote_llm_brain",
    "CodeAgent",
    "CodeAgentResult",
    "CodeChange",
    "CodeGenerationRequest",
    "ExecutionReport",
    "ImprovementProposal",
    "HttpLocalModelTransport",
    "LLMTransport",
    "LocalAIProvider",
    "LocalModelTransport",
    "LocalProviderConnectionError",
    "LocalProviderError",
    "LocalProviderResponseError",
    "MockLLMTransport",
    "OpenAICompatibleTransport",
    "AnthropicTransport",
    "Plan",
    "PlanStep",
    "Planner",
    "ProviderBrain",
    "RemoteLLMBrain",
    "RemoteLLMConfigError",
    "RemoteLLMConnectionError",
    "RemoteLLMError",
    "RemoteLLMResponseError",
    "SelfImprovementManager",
    "ToolResult",
    "UnavailableBrain",
    "ProcessLocalModelTransport",
]

_EXPORTS = {
    "AIProvider": (".brain", "AIProvider"),
    "Brain": (".brain", "Brain"),
    "BrainError": (".brain", "BrainError"),
    "BrainUnavailableError": (".brain", "BrainUnavailableError"),
    "ProviderBrain": (".brain", "ProviderBrain"),
    "UnavailableBrain": (".brain", "UnavailableBrain"),
    "build_local_brain": (".local_provider", "build_local_brain"),
    "build_remote_llm_brain": (".remote_llm", "build_remote_llm_brain"),
    "LLMTransport": (".remote_llm", "LLMTransport"),
    "MockLLMTransport": (".remote_llm", "MockLLMTransport"),
    "OpenAICompatibleTransport": (".remote_llm", "OpenAICompatibleTransport"),
    "AnthropicTransport": (".remote_llm", "AnthropicTransport"),
    "RemoteLLMBrain": (".remote_llm", "RemoteLLMBrain"),
    "RemoteLLMError": (".remote_llm", "RemoteLLMError"),
    "RemoteLLMConfigError": (".remote_llm", "RemoteLLMConfigError"),
    "RemoteLLMConnectionError": (".remote_llm", "RemoteLLMConnectionError"),
    "RemoteLLMResponseError": (".remote_llm", "RemoteLLMResponseError"),
    "CodeAgent": (".code_agent", "CodeAgent"),
    "CodeAgentResult": (".code_agent", "CodeAgentResult"),
    "AgentExecutor": (".executor", "AgentExecutor"),
    "Planner": (".planner", "Planner"),
    "SelfImprovementManager": (".self_improvement", "SelfImprovementManager"),
    "LocalAIProvider": (".local_provider", "LocalAIProvider"),
    "LocalModelTransport": (".local_provider", "LocalModelTransport"),
    "HttpLocalModelTransport": (".local_provider", "HttpLocalModelTransport"),
    "ProcessLocalModelTransport": (".local_provider", "ProcessLocalModelTransport"),
    "LocalProviderError": (".local_provider", "LocalProviderError"),
    "LocalProviderConnectionError": (
        ".local_provider",
        "LocalProviderConnectionError",
    ),
    "LocalProviderResponseError": (
        ".local_provider",
        "LocalProviderResponseError",
    ),
    "CodeChange": (".models", "CodeChange"),
    "CodeGenerationRequest": (".models", "CodeGenerationRequest"),
    "ExecutionReport": (".models", "ExecutionReport"),
    "ImprovementProposal": (".models", "ImprovementProposal"),
    "Plan": (".models", "Plan"),
    "PlanStep": (".models", "PlanStep"),
    "ToolResult": (".models", "ToolResult"),
}


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value
