# ADR 0001: explicit state machines rather than an agent framework

Status: accepted
Date: 2026-09-22

## Context

Both loops in this system are state machines. The supervisor moves an
incident through triage, planning, dispatch, aggregation, decision,
action and verification. An escalation moves through pending, assigned,
and one of six terminal states.

LangGraph, CrewAI, AutoGen and several others would express both. Using
one would also be the conventional choice, and it is what a reader
expects to find.

## Decision

Write both state machines by hand, in `handoff/supervisor/supervisor.py`
and `handoff/escalation/engine.py`.

## Consequences

The argument for the framework is real: less code, a known vocabulary,
and a visualiser. The argument against is that the interesting part of
this project is the transition table itself, and a framework puts a
layer between the reader and the thing they came to look at.

Specifically:

The supervisor pauses mid run and resumes on the same step. That is the
behaviour most likely to be subtly wrong, and writing it out means a
reviewer can check it by reading one file rather than by trusting a
checkpointer they cannot see.

The escalation engine's `tick` is driven by the caller. Frameworks tend
to own the scheduler, and a scheduler you do not own is a deadline you
cannot test at 299 and 300 seconds.

Node names and persisted state map onto a LangGraph implementation
directly, so this is reversible. If the plan ever becomes dynamic per
incident, the argument flips and this decision should be revisited.

The cost is real and worth stating: no visualiser, no community, and
`advance()` is a long method with a loop guard in it.
