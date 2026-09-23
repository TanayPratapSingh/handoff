"""Event types.

Every state change in this system is an event, and the event is written
before the effect is applied. That ordering matters: a crash between the
write and the effect leaves a journal that says "about to" rather than a
journal that says nothing, and "about to" is recoverable.

EventKind is a closed vocabulary on purpose. A new kind of thing happening
is a deliberate change to this file, not a free string invented at a call
site.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from handoff.core.clock import iso
from handoff.core.ids import new_id


class EventKind(StrEnum):
    INCIDENT_OPENED = "incident.opened"
    INCIDENT_CLOSED = "incident.closed"
    INCIDENT_FROZEN = "incident.frozen"
    INCIDENT_RESUMED = "incident.resumed"

    PLAN_BUILT = "plan.built"
    PLAN_REVISED = "plan.revised"

    SUBTASK_ROUTED = "subtask.routed"
    SUBTASK_STARTED = "subtask.started"
    SUBTASK_FINISHED = "subtask.finished"
    SUBTASK_FAILED = "subtask.failed"

    FINDINGS_MERGED = "findings.merged"
    CONFLICT_DETECTED = "conflict.detected"

    ACTION_PROPOSED = "action.proposed"
    ACTION_ALLOWED = "action.allowed"
    ACTION_EXECUTED = "action.executed"
    ACTION_DENIED = "action.denied"
    ACTION_FAILED = "action.failed"

    ESCALATION_RAISED = "escalation.raised"
    ESCALATION_ASSIGNED = "escalation.assigned"
    ESCALATION_DECIDED = "escalation.decided"
    ESCALATION_EXPIRED = "escalation.expired"
    ESCALATION_REASSIGNED = "escalation.reassigned"
    ESCALATION_EXHAUSTED = "escalation.exhausted"

    POLICY_BLOCKED = "policy.blocked"
    AUTONOMY_CHANGED = "autonomy.changed"


@dataclass(frozen=True)
class Event:
    kind: EventKind
    incident_id: str
    at: datetime
    detail: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("evt"))
    actor: str = "system"

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["kind"] = str(self.kind)
        out["at"] = iso(self.at)
        return out

    def summary(self) -> str:
        bits = " ".join(
            f"{k}={v}" for k, v in self.detail.items() if not isinstance(v, dict | list)
        )
        return f"[{iso(self.at)}] {self.kind} {self.incident_id} {bits}".rstrip()
