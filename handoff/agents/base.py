"""What a worker is and what it returns.

A worker answers one question about an incident and returns two kinds of
thing: findings, which are claims about the world, and proposals, which
are actions it thinks somebody should take.

Workers never execute anything. A worker that could act on its own
conclusion would make the supervisor and the escalation ladder optional,
and optional safety is not safety. Proposals go back to the supervisor,
which is the only component that calls a tool.

Every Finding carries the hypotheses it supports and the ones it
contradicts. That is what lets the aggregator notice that two workers
disagree, which is a reason to involve a human that has nothing to do
with how risky the action is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from handoff.tools.registry import ToolRegistry
from handoff.tools.world import World


@dataclass(frozen=True)
class Finding:
    source: str
    claim: str
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    supports: tuple[str, ...] = ()
    contradicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")
        overlap = set(self.supports) & set(self.contradicts)
        if overlap:
            raise ValueError(f"finding both supports and contradicts {sorted(overlap)}")

    def describe(self) -> str:
        return f"{self.source}: {self.claim} (confidence {self.confidence:.2f})"


@dataclass(frozen=True)
class ProposedAction:
    tool: str
    args: dict[str, Any]
    reason: str
    proposed_by: str
    addresses: str = ""

    def describe(self) -> str:
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.args.items()))
        return f"{self.tool}({rendered}) because {self.reason}"


@dataclass
class Subtask:
    id: str
    capability: str
    description: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()


@dataclass
class WorkerResult:
    subtask_id: str
    worker: str
    findings: list[Finding] = field(default_factory=list)
    proposals: list[ProposedAction] = field(default_factory=list)
    ok: bool = True
    error: str = ""

    @classmethod
    def failed(cls, subtask_id: str, worker: str, error: str) -> WorkerResult:
        return cls(subtask_id=subtask_id, worker=worker, ok=False, error=error)


@dataclass
class WorkerContext:
    """Everything a worker is allowed to touch.

    Read only tools only. The registry handed to a worker is filtered by
    the supervisor so that a worker cannot call a mutating tool even by
    name, rather than being trusted not to.
    """

    registry: ToolRegistry
    world: World

    def call(self, tool_name: str, **args: Any) -> Any:
        tool = self.registry.get(tool_name)
        return tool.run(self.world, tool.validate(args))


class Worker(Protocol):
    name: str
    capabilities: frozenset[str]

    def handle(self, subtask: Subtask, ctx: WorkerContext) -> WorkerResult:
        ...
