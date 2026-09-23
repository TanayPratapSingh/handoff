"""Worker registry and capability lookup.

Routing is by declared capability, not by name. A subtask asks for
"metrics" and gets whichever worker claims that capability, so swapping a
worker out is a registration change rather than an edit to the planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from handoff.agents.base import Worker
from handoff.core.errors import UnknownWorkerError


@dataclass
class WorkerRegistry:
    workers: dict[str, Worker] = field(default_factory=dict)

    def register(self, worker: Worker) -> Worker:
        if worker.name in self.workers:
            raise ValueError(f"worker already registered: {worker.name}")
        if not worker.capabilities:
            raise ValueError(f"worker {worker.name} declares no capabilities")
        self.workers[worker.name] = worker
        return worker

    def get(self, name: str) -> Worker:
        if name not in self.workers:
            raise UnknownWorkerError(f"no such worker: {name}")
        return self.workers[name]

    def names(self) -> list[str]:
        return sorted(self.workers)

    def capabilities(self) -> set[str]:
        out: set[str] = set()
        for worker in self.workers.values():
            out |= worker.capabilities
        return out

    def for_capability(self, capability: str) -> Worker:
        matches = sorted(
            (w for w in self.workers.values() if capability in w.capabilities),
            key=lambda w: w.name,
        )
        if not matches:
            raise UnknownWorkerError(
                f"no worker provides capability {capability!r}, "
                f"available: {sorted(self.capabilities())}"
            )
        return matches[0]
