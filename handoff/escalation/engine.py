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
        risk: Risk | None = None,
    ) -> Escalation:
        """Raise an escalation for a proposed action.

        risk overrides the tool's declared level. The supervisor raises the
        effective risk of an action whose diagnosis is contested, and that
        raised level has to pick the rule too. Deciding to escalate at
        medium and then looking up the low rule gives an escalation with an
        empty ladder that exhausts on its first assignment, which reads in
        the journal like a policy decision and is actually a lookup bug.
        """
        effective = risk or tool.risk
        rule = self.policy.rule_for(effective)
        now = self.clock.now()
        esc = Escalation(
            incident_id=incident_id,
            tool=tool.name,
            args=dict(args),
            risk=effective,
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

    # deciding

    def decide(
        self,
        escalation_id: str,
        responder_id: str,
        decision: Decision,
        note: str = "",
        modified_args: dict[str, Any] | None = None,
    ) -> Escalation:
        """Record a human decision.

        A rejection is final and does not ladder onward. The asymmetry is
        deliberate: one person saying no is enough to stop an irreversible
        action, while one person saying yes may not be enough to start it.
        """
        esc = self._escalations[escalation_id]
        if esc.state.is_terminal:
            raise ValueError(f"escalation {esc.id} is already {esc.state}")
        if not esc.attempts:
            raise ValueError(f"escalation {esc.id} has no open attempt to decide")

        attempt = esc.attempts[-1]
        if attempt.responder_id != responder_id:
            raise ValueError(
                f"escalation {esc.id} is assigned to {attempt.responder_id}, "
                f"not {responder_id}"
            )
        attempt.answered = True
        attempt.decision = decision
        attempt.note = note
        esc.state = EscalationState.ASSIGNED

        self._emit(
            EventKind.ESCALATION_DECIDED, esc, actor=responder_id,
            decision=str(decision), note=note, tier=attempt.tier,
        )

        if decision is Decision.REJECT:
            esc.state = EscalationState.REJECTED
            esc.resolved_at = self.clock.now()
            esc.resolution_note = note or f"rejected by {responder_id}"
            self._release(esc)
            return esc

        if decision is Decision.DEFER:
            esc.tier_index += 1
            self._release_one(responder_id)
            return self._assign(esc)

        if decision is Decision.MODIFY:
            if modified_args is None:
                raise ValueError("Decision.MODIFY requires modified_args")
            esc.modified_args = dict(modified_args)

        esc.approvals.append(responder_id)
        if len(esc.approvals) >= esc.quorum:
            esc.state = EscalationState.APPROVED
            esc.resolved_at = self.clock.now()
            esc.resolution_note = (
                f"approved by {', '.join(esc.approvals)}"
                + (" with edited arguments" if esc.modified_args is not None else "")
            )
            self._release(esc)
            return esc

        # Quorum not met. Climb to the next tier for another signature.
        esc.tier_index += 1
        self._release_one(responder_id)
        return self._assign(esc)

    def _release_one(self, responder_id: str | None) -> None:
        if responder_id:
            self.roster.release(responder_id)

    # the clock

    def tick(self) -> list[Escalation]:
        """Fire every deadline that has passed. Returns what changed.

        Callers drive this. Nothing in this system runs on a background
        thread, because a deadline that fires on a timer you cannot control
        is a deadline you cannot test.
        """
        now = self.clock.now()
        fired: list[Escalation] = []
        for esc in list(self._escalations.values()):
            if not esc.is_overdue(now):
                continue
            attempt = esc.attempts[-1]
            self._emit(
                EventKind.ESCALATION_EXPIRED, esc,
                tier=attempt.tier, responder=attempt.responder_id,
                waited_seconds=int((now - attempt.assigned_at).total_seconds()),
                on_expiry=str(esc.on_expiry),
            )
            self._apply_expiry(esc)
            fired.append(esc)
        return fired

    def _apply_expiry(self, esc: Escalation) -> Escalation:
        self._release_one(esc.attempts[-1].responder_id)

        if esc.on_expiry is OnExpiry.ESCALATE:
            esc.tier_index += 1
            if esc.current_tier is None:
                return self._exhaust(esc)
            return self._assign(esc)

        if esc.on_expiry is OnExpiry.HOLD:
            esc.state = EscalationState.HELD
            esc.resolution_note = (
                "held: the incident is frozen until a human acts on this"
            )
            self._emit(EventKind.INCIDENT_FROZEN, esc, why="escalation held on timeout")
            return esc

        if esc.on_expiry is OnExpiry.SAFE_FALLBACK:
            if esc.safe_fallback is None:
                esc.state = EscalationState.DENIED_ON_TIMEOUT
                esc.resolved_at = self.clock.now()
                esc.resolution_note = (
                    f"policy asked for a safe fallback but {esc.tool} declares none, "
                    f"so the action was dropped"
                )
                self._emit(EventKind.ACTION_DENIED, esc, why="no fallback declared")
                return esc
            esc.state = EscalationState.FELL_BACK
            esc.resolved_at = self.clock.now()
            esc.resolution_note = f"nobody answered, ran {esc.safe_fallback} instead"
            self._emit(
                EventKind.ACTION_ALLOWED, esc,
                substituted=esc.safe_fallback, why="safe fallback on timeout",
            )
            return esc

        esc.state = EscalationState.DENIED_ON_TIMEOUT
        esc.resolved_at = self.clock.now()
        esc.resolution_note = "nobody answered in time, action dropped"
        self._emit(EventKind.ACTION_DENIED, esc, why="deadline passed with no answer")
        return esc

    # resolution

    def resolution(self, esc: Escalation) -> Resolution:
        """Translate a terminal escalation into what should now happen."""
        if esc.state is EscalationState.APPROVED:
            return Resolution(esc, True, esc.tool, esc.effective_args, esc.resolution_note)
        if esc.state is EscalationState.FELL_BACK:
            args: dict[str, Any] = {}
            if self.registry is not None and esc.safe_fallback:
                fallback = self.registry.get(esc.safe_fallback)
                args = {
                    f.name: esc.args[f.name] for f in fallback.fields if f.name in esc.args
                }
            return Resolution(esc, True, esc.safe_fallback, args, esc.resolution_note)
        return Resolution(esc, False, None, {}, esc.resolution_note)
