"""The escalation engine.

Four entry points:

raise_for   turn a proposed action into a question for a human
decide      record what a human said
tick        fire every deadline that has passed
open        what is still outstanding

tick is the one that matters. Every other part of this system exists in
plenty of other agent frameworks under one name or another. The part that
is usually missing is a clock that runs whether or not anybody is looking,
and a written down answer for the case where nobody ever replies.

Resolution outcomes, all of them terminal except HELD:

APPROVED            a human, or a quorum of humans, said yes
REJECTED            a human said no, which is final and does not ladder on
FELL_BACK           nobody answered, a strictly safer action ran instead
DENIED_ON_TIMEOUT   nobody answered, the action was dropped
HELD                nobody answered, the incident is frozen until they act
EXHAUSTED           the ladder ran out of humans before a decision
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from handoff.bus.events import Event, EventKind
from handoff.bus.journal import Journal
from handoff.core.clock import Clock, iso
from handoff.core.types import Decision, OnExpiry, Risk
from handoff.escalation.policy import Policy
from handoff.escalation.request import Attempt, Escalation, EscalationState
from handoff.escalation.roster import Roster
from handoff.tools.registry import Tool, ToolRegistry


@dataclass(frozen=True)
class Resolution:
    """What the engine decided should now happen to the proposed action."""

    escalation: Escalation
    should_run: bool
    tool: str | None
    args: dict[str, Any]
    note: str

    @property
    def substituted(self) -> bool:
        return self.should_run and self.tool != self.escalation.tool


class EscalationEngine:
    def __init__(
        self,
        policy: Policy,
        roster: Roster,
        journal: Journal,
        clock: Clock,
        registry: ToolRegistry | None = None,
        backoff: float = 0.5,
    ) -> None:
        self.policy = policy
        self.roster = roster
        self.journal = journal
        self.clock = clock
        self.registry = registry
        self.backoff = backoff
        self._escalations: dict[str, Escalation] = {}

    # queries

    def get(self, escalation_id: str) -> Escalation:
        return self._escalations[escalation_id]

    def all(self) -> list[Escalation]:
        return list(self._escalations.values())

    def open(self) -> list[Escalation]:
        return [e for e in self._escalations.values() if e.state.is_open]

    def for_incident(self, incident_id: str) -> list[Escalation]:
        return [e for e in self._escalations.values() if e.incident_id == incident_id]

    # journal helper

    def _emit(self, kind: EventKind, esc: Escalation, actor: str = "system", **detail) -> Event:
        return self.journal.append(Event(
            kind=kind,
            incident_id=esc.incident_id,
            at=self.clock.now(),
            actor=actor,
            detail={"escalation_id": esc.id, "tool": esc.tool, **detail},
        ))

    # raising

    def raise_for(
        self,
        incident_id: str,
        tool: Tool,
        args: dict[str, Any],
        reason: str,
    ) -> Escalation:
        rule = self.policy.rule_for(tool.risk)
        now = self.clock.now()
        esc = Escalation(
            incident_id=incident_id,
            tool=tool.name,
            args=dict(args),
            risk=tool.risk,
            reason=reason,
            blast_radius=tool.blast_radius,
            ladder=rule.ladder,
            deadline_seconds=rule.deadline_seconds,
            on_expiry=rule.on_expiry,
            created_at=now,
            quorum=rule.quorum,
            required_skill=rule.required_skill,
            safe_fallback=tool.safe_fallback,
        )
        self._escalations[esc.id] = esc
        self._emit(
            EventKind.ESCALATION_RAISED, esc,
            risk=str(esc.risk), reason=reason, ladder=list(esc.ladder),
            on_expiry=str(esc.on_expiry), quorum=esc.quorum,
        )
        self._assign(esc)
        return esc

    def _assign(self, esc: Escalation) -> Escalation:
        """Page somebody on the current tier, laddering past empty tiers."""
        while esc.current_tier is not None:
            tier = esc.current_tier
            already = set(esc.approvals)
            pool = [
                r for r in self.roster.candidates(tier, esc.required_skill)
                if r.id not in already
            ]
            deadline = esc.next_deadline(self.clock.now(), self.backoff)
            if not pool:
                esc.attempts.append(Attempt(
                    tier=tier, responder_id=None,
                    assigned_at=self.clock.now(), deadline=deadline,
                ))
                self._emit(
                    EventKind.ESCALATION_REASSIGNED, esc,
                    tier=tier, responder=None, why="no responder with capacity on this tier",
                )
                esc.tier_index += 1
                continue
            chosen = pool[0]
            self.roster.acquire(chosen.id)
            esc.attempts.append(Attempt(
                tier=tier, responder_id=chosen.id,
                assigned_at=self.clock.now(), deadline=deadline,
            ))
            esc.state = EscalationState.ASSIGNED
            self._emit(
                EventKind.ESCALATION_ASSIGNED, esc,
                tier=tier, responder=chosen.id, deadline=iso(deadline),
            )
            return esc
        return self._exhaust(esc)

    def _exhaust(self, esc: Escalation) -> Escalation:
        esc.state = EscalationState.EXHAUSTED
        esc.resolved_at = self.clock.now()
        esc.resolution_note = (
            f"ladder exhausted after {len(esc.attempts)} attempts: "
            f"{', '.join(esc.tiers_tried()) or 'no tiers'}"
        )
        self._emit(
            EventKind.ESCALATION_EXHAUSTED, esc,
            tiers_tried=esc.tiers_tried(), attempts=len(esc.attempts),
        )
        self._release(esc)
        return esc

    def _release(self, esc: Escalation) -> None:
        for attempt in esc.attempts:
            if attempt.responder_id:
                self.roster.release(attempt.responder_id)
