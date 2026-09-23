"""The vocabulary the whole system agrees on.

Four enums carry most of the meaning in this project:

Risk        how much damage an action can do
Autonomy    how much the operator currently trusts the system
Decision    what a human said when asked
OnExpiry    what happens when the human said nothing at all

The last one is the one most systems leave undefined. An escalation with no
declared expiry behaviour is a system that hangs, and a hung incident
response is worse than a wrong one because nobody is watching it fail.
"""

from __future__ import annotations

from enum import StrEnum


class Risk(StrEnum):
    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _RISK_ORDER[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Risk):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Risk):
            return NotImplemented
        return self.rank <= other.rank


_RISK_ORDER: dict[Risk, int] = {
    Risk.READ_ONLY: 0,
    Risk.LOW: 1,
    Risk.MEDIUM: 2,
    Risk.HIGH: 3,
    Risk.CRITICAL: 4,
}


class Autonomy(StrEnum):
    """How much the system is allowed to do without asking.

    OBSERVE and SUGGEST never execute anything that mutates. GUARDED is the
    interesting setting and the default: act below the policy bar, escalate
    at or above it.
    """

    OBSERVE = "observe"
    SUGGEST = "suggest"
    GUARDED = "guarded"
    AUTONOMOUS = "autonomous"

    @property
    def may_execute(self) -> bool:
        return self in (Autonomy.GUARDED, Autonomy.AUTONOMOUS)


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"
    DEFER = "defer"


class OnExpiry(StrEnum):
    """What the deadline does when it fires with no human answer.

    DENY          drop the action, record the miss, continue the incident
    SAFE_FALLBACK run the declared safer action instead, if the tool has one
    ESCALATE      push to the next tier of the ladder
    HOLD          freeze the incident and keep it frozen until a human acts

    There is deliberately no ALLOW. A policy that auto approves an action
    because nobody looked at it in time has converted an escalation into a
    delay, and this system refuses to offer that as a config option. ADR
    0004 records the argument.
    """

    DENY = "deny"
    SAFE_FALLBACK = "safe_fallback"
    ESCALATE = "escalate"
    HOLD = "hold"


class Severity(StrEnum):
    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"
    SEV4 = "sev4"

    @property
    def rank(self) -> int:
        return {"sev1": 0, "sev2": 1, "sev3": 2, "sev4": 3}[self.value]
