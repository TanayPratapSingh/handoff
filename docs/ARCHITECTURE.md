# Architecture

## The shape

```
                    Incident
                       |
                  [ Supervisor ]  <-- the only component that executes
                   /    |     \
         plan   dispatch   aggregate
                   /           |
        [ Worker registry ]  [ Aggregator ]
         logs                  supports / contradicts
         metrics               contested hypotheses
         replication                |
         runbook                    v
         remediation          effective risk
                                    |
                              needs a human?
                                 /      \
                               no        yes
                               |          |
                            execute  [ Escalation engine ]
                                          |
                                     policy table  (config/policy.yaml)
                                     roster        (config/roster.yaml)
                                          |
                                   assign -> deadline -> tick
                                          |
                            approve / reject / modify / defer
                                  / silence -> on_expiry
                                          |
                     deny | safe_fallback | escalate | hold
                                          |
                                    [ Journal ]  append only
```

## Layers

`handoff/core` types, injectable clock, ids, errors, YAML subset reader.
Depends on nothing.

`handoff/bus` the closed event vocabulary and the append only journal
with an optional JSONL sink. Every state change is written before its
effect is applied.

`handoff/tools` tool registry, argument schemas, and a simulated cluster.
A tool carries risk, reversibility, a plain words blast radius, and the
name of a strictly lower risk substitute where one exists.

`handoff/agents` the worker protocol and five workers. Four analysts that
report and one planner that proposes. No worker executes anything.

`handoff/escalation` the roster, the policy table, the escalation record
and the engine. Owns deadlines.

`handoff/supervisor` decomposition, aggregation, and the orchestration
state machine. The only component that calls a mutating tool.

`handoff/evalsvc` scenario parsing and the scenario runner.

Dependencies point one way: supervisor depends on escalation, agents and
tools; escalation depends on tools and core; core depends on nothing.

## The three mechanisms worth reading

### Risk is a property of the tool, not of the caller

A tool declares its own risk, whether it is reversible, and what its
safer substitute is. `build_registry` refuses to construct a registry
where a declared substitute is missing, points at itself, or is not
strictly lower risk. That check runs at import, so a broken declaration
fails on startup rather than at the moment it is needed.

### Disagreement is escalated, not averaged

The aggregator tracks, per hypothesis, which workers support it and which
contradict it. A hypothesis with voices on both sides is contested.
Contested is not the same as low scoring: two confident workers reaching
opposite conclusions and two hesitant ones agreeing both net out near
zero, and only the first should stop the machine.

An action addressing a contested hypothesis has its effective risk raised
one level, which can push a low risk action over the escalation bar.
Uncertainty about the diagnosis and danger in the fix are different
things with the same remedy.

### The deadline is the product

`EscalationEngine.tick` fires every deadline that has passed and applies
the rule's declared `on_expiry`. Nothing sleeps and nothing runs on a
background thread, so every deadline is testable at its exact boundary.

The four expiry behaviours and the reason there is no fifth are in
ADR 0004.

## Extension points

Replace a rule based analyst with an LLM backed one by implementing
`Worker`: a `name`, a `capabilities` set, and `handle`. Workers receive a
registry filtered to read only tools, so a new worker cannot reach a
mutating tool by name.

Replace the simulated cluster by giving each tool a `run` that calls a
real API. The signature is `(world, validated_args)`.

Replace the static plan in `handoff/supervisor/planner.py` with a
generated one. ADR 0001 notes that this is the change that would justify
moving to a graph framework.
