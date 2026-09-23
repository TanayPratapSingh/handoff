"""Argument schemas for tools.

Validation happens before a proposal reaches a human, not after they
approve it. Asking somebody to approve an action whose arguments turn out
to be malformed wastes the one resource this system is careful with, which
is human attention.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from handoff.core.errors import ValidationError


@dataclass(frozen=True)
class Field:
    name: str
    type: type
    required: bool = True
    default: Any = None
    choices: tuple[Any, ...] | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    description: str = ""

    def check(self, tool: str, value: Any) -> Any:
        if value is None:
            if self.required:
                raise ValidationError(tool, self.name, "is required")
            return self.default
        # bool is a subclass of int in Python, so isinstance(True, int) is
        # True. Without this guard scale_deployment(replicas=True) validates
        # and scales the service to one replica. Both directions are closed:
        # a bool is never accepted as a number, and a number is never
        # accepted as a bool.
        if isinstance(value, bool) and self.type is not bool:
            raise ValidationError(
                tool, self.name, f"expected {self.type.__name__}, got bool"
            )
        if self.type is bool and not isinstance(value, bool):
            raise ValidationError(tool, self.name, f"expected bool, got {type(value).__name__}")
        if self.type is float and isinstance(value, int):
            value = float(value)
        if not isinstance(value, self.type):
            raise ValidationError(
                tool, self.name, f"expected {self.type.__name__}, got {type(value).__name__}"
            )
        if self.choices is not None and value not in self.choices:
            raise ValidationError(
                tool, self.name, f"{value!r} not in {list(self.choices)}"
            )
        if self.minimum is not None and value < self.minimum:
            raise ValidationError(tool, self.name, f"{value} is below minimum {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise ValidationError(tool, self.name, f"{value} is above maximum {self.maximum}")
        return value


def validate(tool: str, fields: tuple[Field, ...], args: dict[str, Any]) -> dict[str, Any]:
    """Return a normalised copy of args, or raise on the first problem."""
    known = {f.name for f in fields}
    for key in args:
        if key not in known:
            raise ValidationError(tool, key, f"unknown argument, expected one of {sorted(known)}")
    return {f.name: f.check(tool, args.get(f.name)) for f in fields}
