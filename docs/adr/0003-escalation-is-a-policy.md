# ADR 0003: escalation is a policy, not a callback

Status: accepted
Date: 2026-09-22

## Context

The common shape for human in the loop is a callback. The agent reaches
a risky action, calls `confirm(action)`, and blocks until the function
returns.

It is the obvious design and it is wrong in three ways that only show up
in production.

It blocks. A thread parked on an input queue for six hours is a resource
leak with a human attached.

It does not say who. `confirm()` asks whoever is looking at the terminal.
Real escalation is a routing problem: which tier, which skill, who is
already holding three other pages.

It has no deadline. The function returns when it returns, and the case
where it never returns is undefined.

## Decision

Escalation is a declarative policy table keyed by risk, in
`config/policy.yaml`. Each rule states the ladder of tiers, the deadline
in seconds, the quorum, the required skill, and what happens on expiry.

`EscalationEngine.raise_for` records the question and returns
immediately. `tick` fires deadlines. The supervisor returns
`AWAITING_HUMAN` and the caller drives the clock.

## Consequences

The policy is data, so it is reviewable in a pull request by somebody who
does not read Python, and it is diffable when it changes after an
incident review.

Load time validation catches the failures that otherwise only appear
during an incident: a rule that requires approval without stating
`on_expiry`, a quorum larger than its own ladder, a tier in a ladder that
no responder stands on, and a `safe_fallback` that is missing, self
referential or not actually lower risk.

Nothing blocks, so the whole system is testable with a `ManualClock` and
the suite runs in under a second with no sleeps.

The cost is that the caller has to drive `tick`. In this repository that
is the CLI and the scenario runner. A deployment would need a real
scheduler, and that scheduler is not written here. The README says so.
