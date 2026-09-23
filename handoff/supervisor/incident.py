"""The incident record and the run state that hangs off it."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from handoff.agents.base import ProposedAction, Subtask, WorkerResult
from handoff.core.ids import new_id
from handoff.core.types import Severity
from handoff.supervisor.aggregator import Aggregate


class RunState(StrEnum):
    TRIAGE = "triage"
    PLANNING = "planning"
    DISPATCHING = "dispatching"
    AGGREGATING = "aggregating"
    DECIDING = "deciding"
    AWAITING_HUMAN = "awaiting_human"
    ACTING = "acting"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    FROZEN = "frozen"
    ABANDONED = "abandoned"

    @property
    def is_terminal(self) -> bool:
        return self in (RunState.RESOLVED, RunState.FROZEN, RunState.ABANDONED)

    @property
    def is_blocked(self) -> bool:
        return self is RunState.AWAITING_HUMAN


@dataclass(frozen=True)
class Incident:
    title: str
    service: str
    symptom: str
    severity: Severity = Severity.SEV2
    id: str = field(default_factory=lambda: new_id("inc"))

    def describe(self) -> str:
        return f"{self.id} [{self.severity}] {self.title} ({self.service}: {self.symptom})"


@dataclass
class ExecutedAction:
    tool: str
    args: dict[str, Any]
    result: Any
    at: datetime
    approved_by: str = ""
    substituted_for: str = ""
    ok: bool = True
    error: str = ""


@dataclass
class IncidentRun:
    """Everything known about one incident in progress.

    This is the object that survives a pause. A run waiting on a human is
    fully described by this record, which is what makes resuming after a
    deadline a state transition rather than a rebuild.
    """

    incident: Incident
    state: RunState = RunState.TRIAGE
    subtasks: list[Subtask] = field(default_factory=list)
    results: list[WorkerResult] = field(default_factory=list)
    aggregate: Aggregate = field(default_factory=Aggregate)
    queue: list[ProposedAction] = field(default_factory=list)
    executed: list[ExecutedAction] = field(default_factory=list)
    escalation_ids: list[str] = field(default_factory=list)
    blocked_on: str | None = None
    notes: list[str] = field(default_factory=list)

    def note(self, text: str) -> str:
        self.notes.append(text)
        return text

    @property
    def acted(self) -> bool:
        return any(a.ok for a in self.executed)

    def report(self) -> str:
        lines = [
            self.incident.describe(),
            f"state: {self.state}",
        ]
        if self.aggregate.hypotheses:
            lines.append("hypotheses:")
            lines += [f"  {h}" for h in self.aggregate.summary().splitlines()]
        if self.executed:
            lines.append("actions taken:")
            for action in self.executed:
                detail = f"  {action.tool}({action.args})"
                if action.substituted_for:
                    detail += f"  [substituted for {action.substituted_for}]"
                if action.approved_by:
                    detail += f"  [approved by {action.approved_by}]"
                if not action.ok:
                    detail += f"  [FAILED: {action.error}]"
                lines.append(detail)
        else:
            lines.append("actions taken: none")
        if self.notes:
            lines.append("notes:")
            lines += [f"  {n}" for n in self.notes]
        return "\n".join(lines)
