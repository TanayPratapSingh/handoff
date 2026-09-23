"""The tool registry.

A Tool carries more than a callable. It carries the facts the escalation
layer needs in order to decide whether a human has to look at it:

risk           how much damage the action can do
reversible     whether the action can be undone at all
blast_radius   plain words, shown to the human, no jargon
safe_fallback  the name of a strictly safer tool to run instead

safe_fallback is what OnExpiry.SAFE_FALLBACK reaches for. A tool with no
safer version declares None, and the policy that names SAFE_FALLBACK for
a tier containing such a tool is rejected at load time rather than
discovered at 3am.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from handoff.core.errors import UnknownToolError
from handoff.core.types import Risk
from handoff.tools.schema import Field, validate
from handoff.tools.world import World


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    risk: Risk
    fields: tuple[Field, ...] = ()
    run: Callable[[World, dict[str, Any]], Any] | None = None
    reversible: bool = True
    blast_radius: str = ""
    safe_fallback: str | None = None

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        return validate(self.name, self.fields, args)

    def describe(self, args: dict[str, Any]) -> str:
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(args.items()))
        return f"{self.name}({rendered})"


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> Tool:
        if tool.name in self.tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self.tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            raise UnknownToolError(f"no such tool: {name}")
        return self.tools[name]

    def has(self, name: str) -> bool:
        return name in self.tools

    def names(self) -> list[str]:
        return sorted(self.tools)

    def by_risk(self, risk: Risk) -> list[Tool]:
        return [t for t in self.tools.values() if t.risk == risk]

    def at_or_above(self, risk: Risk) -> list[Tool]:
        return [t for t in self.tools.values() if t.risk.rank >= risk.rank]

    def check_fallbacks(self) -> list[str]:
        """Return a list of problems with declared fallbacks.

        A fallback must exist, must be a different tool, and must be
        strictly lower risk. Returning the problems rather than raising
        lets the caller report all of them at once.
        """
        problems: list[str] = []
        for tool in self.tools.values():
            target = tool.safe_fallback
            if target is None:
                continue
            if target not in self.tools:
                problems.append(f"{tool.name}: fallback {target!r} is not registered")
                continue
            if target == tool.name:
                problems.append(f"{tool.name}: fallback points at itself")
                continue
            if self.tools[target].risk.rank >= tool.risk.rank:
                problems.append(
                    f"{tool.name} ({tool.risk}): fallback {target} "
                    f"({self.tools[target].risk}) is not lower risk"
                )
        return problems
