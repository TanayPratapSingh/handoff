# ADR 0004: there is no ALLOW on expiry

Status: accepted
Date: 2026-09-22

## Context

`OnExpiry` says what happens when an escalation's deadline passes with no
human answer. The obvious set of options is deny, allow, escalate, hold.

Allow is the one people ask for. The argument is reasonable on its face:
during a severity one incident, an action nobody objected to within five
minutes is probably fine, and blocking it costs real downtime.

## Decision

`OnExpiry` has four members: `DENY`, `SAFE_FALLBACK`, `ESCALATE`, `HOLD`.
There is no `ALLOW`, and `Policy.from_config` rejects the string with an
error naming the four that exist.

`tests/test_types.py::TestOnExpiry::test_there_is_no_allow_on_expiry`
asserts its absence, so adding it means deleting a test whose docstring
explains why it should not exist.

## Consequences

Approval on timeout is not approval. It is the absence of a decision,
recorded as though it were a decision. The journal afterwards says the
action was allowed, and nothing in that record distinguishes a considered
yes from nobody having looked.

That distinction is the entire value of the audit trail. An escalation
ladder whose terminal state can be "ran it anyway" is a delay mechanism
wearing the costume of a control.

The operational objection stands, so it is answered with `SAFE_FALLBACK`
instead. A tool declares a strictly lower risk substitute, and on timeout
that substitute runs. The database is not failed over, it is put into
read only mode. Something happens, it is the conservative thing, and the
record says plainly that it happened because nobody answered.

Where no safer action exists, the answer is `HOLD`: freeze the incident
and keep it frozen. That is a worse outcome than a timely human decision
and it is meant to be. The remedy for a hold that hurt is a better rota,
not a policy that approves things nobody read.

The cost is that a team who genuinely wants timeout approval cannot have
it without editing the enum, and the file will argue with them when they
try. That is intentional.
