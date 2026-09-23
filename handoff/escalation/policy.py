"""When to escalate, to whom, for how long, and what happens on silence.

A policy is a table keyed by risk. Each row answers four questions, and
the fourth is the one most systems never answer:

1. does this need a human at all, at the current autonomy level
2. which tiers may approve it, in order
3. how long does the first tier get
4. what happens when the deadline passes with no answer

Question four has no safe default, so there is none. Every rule states
on_expiry explicitly and a rule that omits it is a ConfigError.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from handoff.core.errors import ConfigError
from handoff.core.miniyaml import load
from handoff.core.types import Autonomy, OnExpiry, Risk


@dataclass(frozen=True)
class Rule:
    risk: Risk
    requires_approval: bool
    ladder: tuple[str, ...]
    deadline_seconds: int
    on_expiry: OnExpiry
    quorum: int = 1
    required_skill: str | None = None

    def __post_init__(self) -> None:
        if self.requires_approval and not self.ladder:
            raise ConfigError(f"rule for {self.risk}: requires approval but the ladder is empty")
        if self.deadline_seconds <= 0 and self.requires_approval:
            raise ConfigError(f"rule for {self.risk}: deadline must be positive")
        if self.quorum < 1:
            raise ConfigError(f"rule for {self.risk}: quorum must be at least 1")
        if self.quorum > len(self.ladder) and self.requires_approval:
            raise ConfigError(
                f"rule for {self.risk}: quorum {self.quorum} exceeds ladder length "
                f"{len(self.ladder)}, so it can never be satisfied"
            )


@dataclass(frozen=True)
class Policy:
    rules: dict[Risk, Rule]
    autonomy: Autonomy = Autonomy.GUARDED
    escalate_at_or_above: Risk = Risk.MEDIUM

    def rule_for(self, risk: Risk) -> Rule:
        if risk not in self.rules:
            raise ConfigError(f"no policy rule for risk {risk}")
        return self.rules[risk]

    def needs_human(self, risk: Risk) -> bool:
        """Whether an action at this risk must be approved before it runs.

        Autonomy is applied on top of the table rather than baked into it,
        so the same policy file behaves correctly at every autonomy level
        and switching level does not mean editing rules.
        """
        if self.autonomy is Autonomy.AUTONOMOUS:
            return False
        if not self.autonomy.may_execute:
            return risk.rank > Risk.READ_ONLY.rank
        if risk.rank < self.escalate_at_or_above.rank:
            return False
        return self.rule_for(risk).requires_approval

    def forbids(self, risk: Risk) -> bool:
        """Actions this autonomy level will not take even with approval."""
        if self.autonomy is Autonomy.OBSERVE:
            return risk.rank > Risk.READ_ONLY.rank
        if self.autonomy is Autonomy.SUGGEST:
            return risk.rank > Risk.READ_ONLY.rank
        return False

    def with_autonomy(self, autonomy: Autonomy) -> Policy:
        return Policy(
            rules=self.rules,
            autonomy=autonomy,
            escalate_at_or_above=self.escalate_at_or_above,
        )

    @classmethod
    def from_config(cls, path: str | Path) -> Policy:
        doc = load(path)
        if not isinstance(doc, dict):
            raise ConfigError(f"{path}: expected a mapping at the top level")
        rules: dict[Risk, Rule] = {}
        for name, body in (doc.get("rules") or {}).items():
            try:
                risk = Risk(name)
            except ValueError as exc:
                raise ConfigError(f"{path}: unknown risk level {name!r}") from exc
            if not isinstance(body, dict):
                raise ConfigError(f"{path}: rule {name!r} must be a mapping")
            requires = body.get("requires_approval", True)
            if requires and "on_expiry" not in body:
                raise ConfigError(
                    f"{path}: rule {name!r} requires approval but does not state "
                    f"on_expiry. There is no safe default for what happens when "
                    f"nobody answers, so it has to be written down."
                )
            expiry_name = body.get("on_expiry", OnExpiry.DENY.value)
            try:
                on_expiry = OnExpiry(expiry_name)
            except ValueError as exc:
                raise ConfigError(
                    f"{path}: rule {name!r} has unknown on_expiry {expiry_name!r}, "
                    f"expected one of {[m.value for m in OnExpiry]}"
                ) from exc
            rules[risk] = Rule(
                risk=risk,
                requires_approval=requires,
                ladder=tuple(body.get("ladder") or ()),
                deadline_seconds=int(body.get("deadline_seconds", 0)),
                on_expiry=on_expiry,
                quorum=int(body.get("quorum", 1)),
                required_skill=body.get("required_skill"),
            )
        missing = [r for r in Risk if r not in rules]
        if missing:
            raise ConfigError(f"{path}: no rule for risk levels {[str(m) for m in missing]}")
        autonomy = Autonomy(doc.get("autonomy", Autonomy.GUARDED.value))
        threshold = Risk(doc.get("escalate_at_or_above", Risk.MEDIUM.value))
        return cls(rules=rules, autonomy=autonomy, escalate_at_or_above=threshold)
