# handoff: working context

## What this is

Supervisor orchestrated agents whose escalations have deadlines. The
thesis: an agent that blocks forever on an unanswered approval prompt is
worse than one that never asked, because the incident is still burning
and nothing is watching it. Escalation is therefore a routing problem
with deadlines, ownership and a declared behaviour for silence, and it
has its own layer.

Read `README.md` and `docs/ARCHITECTURE.md` before structural changes.
The four ADRs in `docs/adr/` record decisions that should not be
silently reversed.

## Current state

Everything in this repository has been executed. There is no
written but never run code, which is a deliberate contrast to how this
kind of project usually accretes.

Verified by running: all 212 tests, all 11 scenarios, the four act demo,
the policy and roster commands, and a ruff check plus format pass.

What is simulated, and labelled as such in the README: the cluster is a
dataclass, the five workers are deterministic rules rather than models,
there is no scheduler driving `tick`, and nothing is subscribed to the
journal.

## House rules

1. **Never widen a risk level to make something run.** If a policy rule
   is blocking an action, the fix is to understand why, not to move the
   action down a tier or raise `escalate_at_or_above`. The threshold is
   the product.
2. **Never add `OnExpiry.ALLOW`.** ADR 0004 carries the argument and
   `tests/test_types.py` asserts its absence. Adding it means deleting a
   test whose docstring explains why it should not exist.
3. **Never invent a number.** Every figure in the README traces to a
   command in the README. Anything produced by the simulated cluster or
   the rule based workers says so in the same sentence.
4. **No em dashes** in any file, comment, commit message or output.
5. **No hyphens in compound phrases** like "real time" or "end to end"
   in prose.
6. **Keep the core dependency free.** Everything under `handoff/`
   imports stdlib only. That is ADR 0002 and it is what lets CI run with
   no install step.
7. **Report failures rather than hiding them.** The README has a section
   naming three bugs found during the build. Keep that section honest as
   more turn up.

## Commands

```bash
python3 -m unittest discover -s tests          # 212 tests, no install needed
python3 -m handoff.cli demo                    # four act walkthrough
python3 -m handoff.cli scenarios --dir evals/scenarios
python3 -m handoff.cli policy                  # print the policy table
python3 -m handoff.cli roster                  # print the on call roster
python3 -m ruff check handoff tests
python3 -m ruff format --check handoff tests
```

## Where to work next

In rough order of how much each would improve the project.

1. **A scheduler for `tick`.** The most honest gap. Everything else
   about the deadline layer is real and nothing calls it on a timer.
2. **One LLM backed worker.** Implement `Worker` over an existing
   analyst and find out whether the escalation layer holds up when the
   findings are non deterministic. That is the open question the README
   admits it does not answer.
3. **A notification channel on `Journal.subscribe`.** The hook exists
   and nothing attaches to it.
4. **Rotation in the roster.** Currently seven static people. No
   schedule, no timezones, no handover.
5. **More scenarios.** Eleven is enough to pin the behaviours that
   exist. The gaps worth filling are concurrent incidents competing for
   the same responder, and a responder who approves after the deadline
   has already fired.

## Deferred, and fine to stay deferred

- A real cluster integration. The `World` dataclass is the seam and
  swapping it is a `run` signature away, but nothing about the
  orchestration gets more interesting once it is real.
- A web UI for approvals. The `Decision` API is the thing a UI would
  call, and building the UI teaches nothing the CLI does not.
