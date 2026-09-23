"""Error types.

Each error names the layer that raises it. A caller that catches
HandoffError catches everything this system raises on purpose, and nothing
it raises by accident.
"""

from __future__ import annotations


class HandoffError(Exception):
    """Base for every error this system raises deliberately."""


class ConfigError(HandoffError):
    """A config file is missing, malformed, or internally inconsistent."""


class ValidationError(HandoffError):
    """Tool arguments failed their schema."""

    def __init__(self, tool: str, field: str, message: str) -> None:
        self.tool = tool
        self.field = field
        super().__init__(f"{tool}.{field}: {message}")


class UnknownToolError(HandoffError):
    """A plan referenced a tool that is not in the registry."""


class UnknownWorkerError(HandoffError):
    """The router could not find a worker for a subtask."""


class NoRouteError(HandoffError):
    """An escalation could not be routed to any human at any tier."""

    def __init__(self, escalation_id: str, tried: list[str]) -> None:
        self.escalation_id = escalation_id
        self.tried = tried
        super().__init__(
            f"escalation {escalation_id} exhausted every tier: {', '.join(tried) or 'none'}"
        )


class PolicyViolation(HandoffError):
    """An action was attempted that the active policy forbids outright."""


class StateError(HandoffError):
    """A state machine was driven into a transition it does not define."""
