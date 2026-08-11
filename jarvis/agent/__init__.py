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
    "CodeAgent",
    "CodeAgentResult",
    "CodeChange",
    "CodeGenerationRequest",
    "ExecutionReport",
    "ImprovementProposal",
    "Plan",
    "PlanStep",
    "Planner",
    "ProviderBrain",
    "SelfImprovementManager",
    "ToolResult",
    "UnavailableBrain",
]

_EXPORTS = {
    "AIProvider": (".brain", "AIProvider"),
    "Brain": (".brain", "Brain"),
    "BrainError": (".brain", "BrainError"),
    "BrainUnavailableError": (".brain", "BrainUnavailableError"),
    "ProviderBrain": (".brain", "ProviderBrain"),
    "UnavailableBrain": (".brain", "UnavailableBrain"),
    "CodeAgent": (".code_agent", "CodeAgent"),
    "CodeAgentResult": (".code_agent", "CodeAgentResult"),
    "AgentExecutor": (".executor", "AgentExecutor"),
    "Planner": (".planner", "Planner"),
    "SelfImprovementManager": (".self_improvement", "SelfImprovementManager"),
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
