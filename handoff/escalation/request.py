"""The escalation record.

One escalation is one question put to one human at a time, with a
deadline, a position on a ladder, and a declared behaviour for silence.

The record keeps its whole history rather than just its current state.
When somebody asks later why an action ran, the answer has to include who
was asked, who did not answer, and how long they were given.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from handoff.core.clock import iso
from handoff.core.ids import new_id
from handoff.core.types import Decision, OnExpiry, Risk


class EscalationState(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    APPROVED = "approved"
    REJECTED = "rejected"
    FELL_BACK = "fell_back"
    DENIED_ON_TIMEOUT = "denied_on_timeout"
    HELD = "held"
    EXHAUSTED = "exhausted"

    @property
    def is_open(self) -> bool:
        return self in (EscalationState.PENDING, EscalationState.ASSIGNED,
                        EscalationState.HELD)

    @property
    def is_terminal(self) -> bool:
        return not self.is_open


@dataclass
class Attempt:
    """One page to one person on one tier."""

    tier: str
    responder_id: str | None
    assigned_at: datetime
    deadline: datetime
    answered: bool = False
    decision: Decision | None = None
    note: str = ""

    def describe(self) -> str:
        who = self.responder_id or "nobody available"
        verdict = str(self.decision) if self.answered else "no answer"
        return f"{self.tier}/{who} by {iso(self.deadline)}: {verdict}"


@dataclass
class Escalation:
    incident_id: str
    tool: str
    args: dict[str, Any]
    risk: Risk
    reason: str
    blast_radius: str
    ladder: tuple[str, ...]
    deadline_seconds: int
    on_expiry: OnExpiry
    created_at: datetime
    quorum: int = 1
    required_skill: str | None = None
    safe_fallback: str | None = None
    id: str = field(default_factory=lambda: new_id("esc"))
    state: EscalationState = EscalationState.PENDING
    tier_index: int = 0
    attempts: list[Attempt] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    modified_args: dict[str, Any] | None = None
    resolved_at: datetime | None = None
    resolution_note: str = ""

    @property
    def current_tier(self) -> str | None:
        if self.tier_index >= len(self.ladder):
            return None
        return self.ladder[self.tier_index]

    @property
    def assignee(self) -> str | None:
        return self.attempts[-1].responder_id if self.attempts else None

    @property
    def deadline(self) -> datetime | None:
        return self.attempts[-1].deadline if self.attempts else None

    @property
    def effective_args(self) -> dict[str, Any]:
        """What would actually run, honouring an approver's edits."""
        return self.modified_args if self.modified_args is not None else self.args

    @property
    def approved(self) -> bool:
        return self.state is EscalationState.APPROVED

    def tiers_tried(self) -> list[str]:
        return [a.tier for a in self.attempts]

    def is_overdue(self, now: datetime) -> bool:
        if self.state is not EscalationState.ASSIGNED:
            return False
        current = self.deadline
        return current is not None and now >= current

    def next_deadline(self, now: datetime, backoff: float = 1.0) -> datetime:
        """Deadline for the next attempt.

        Later tiers get a shorter window, not a longer one. By the time an
        escalation reaches tier three the incident has already been open
        for the full budget of tiers one and two, so the remaining urgency
        is higher and the patience should be lower.
        """
        seconds = max(30, int(self.deadline_seconds * (backoff ** self.tier_index)))
        return now + timedelta(seconds=seconds)

    def summary(self) -> str:
        return (
            f"{self.id} {self.tool} risk={self.risk} state={self.state} "
            f"tier={self.current_tier or 'exhausted'} "
            f"attempts={len(self.attempts)}"
        )

    def audit(self) -> str:
        lines = [
            f"escalation {self.id} on incident {self.incident_id}",
            f"  action        {self.tool}({self.args})",
            f"  risk          {self.risk}, blast radius: {self.blast_radius}",
            f"  reason        {self.reason}",
            f"  on expiry     {self.on_expiry}",
            f"  raised at     {iso(self.created_at)}",
        ]
        for i, attempt in enumerate(self.attempts, 1):
            lines.append(f"  attempt {i}     {attempt.describe()}")
        lines.append(f"  outcome       {self.state} {self.resolution_note}".rstrip())
        return "\n".join(lines)
