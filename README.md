# handoff

Supervisor orchestrated agents whose escalations have deadlines.

Most human in the loop is a modal dialog that blocks forever. The agent
reaches something risky, calls `confirm()`, and waits. It does not say
who is being asked, it does not say how long they have, and it has no
answer at all for the case that actually happens at 3am, which is that
nobody replies.

An agent that hangs on an unanswered prompt is worse than one that never
asked, because the incident is still burning and now nothing is watching
it. This repository takes the position that escalation is a routing
problem with deadlines, ownership and a declared behaviour for silence,
and builds the rest of the system around that.

The domain is incident response on a simulated cluster. The domain is
not the point. The escalation layer is.

## The one behaviour to look at

```
  proposed   failover_database({'target': 'node-b'})
  risk       high, reversible=False
  blast      every writer reconnects, in flight transactions are lost
  fallback   enable_read_only
  on expiry  safe_fallback
  paged      ana, 180s to answer

  Nobody answers.

  enable_read_only({})   <- substituted for failover_database
```

The database was not failed over and the system did not sit still. It
put the database into read only mode, which is the substitute the
failover tool declares: writes are rejected and checkout degrades, but
no in flight transaction is lost and a human can undo it on arrival.

The policy could not have chosen to just run the failover after the
timeout. `OnExpiry` has four members and none of them approves an action
nobody looked at. See [ADR 0004](docs/adr/0004-no-allow-on-expiry.md).

## Run it

No install step, no virtualenv, no dependencies.

```bash
python3 -m unittest discover -s tests
```

```bash
python3 -m handoff.cli demo
```

```bash
python3 -m handoff.cli scenarios --dir evals/scenarios
python3 -m handoff.cli policy
python3 -m handoff.cli roster
```

## What it does

A supervisor decomposes an incident, fans out to five workers, merges
what they found, and decides what to do about it. Four of the workers
report and one proposes. None of them executes anything: workers are
handed a tool registry filtered to read only tools, so a worker cannot
reach a mutating tool by name rather than being trusted not to.

The supervisor is the only component that calls a mutating tool, which
is what makes the escalation ladder load bearing rather than advisory.

Three mechanisms carry most of the weight.

**Risk lives on the tool.** Each tool declares its risk, whether it is
reversible, a plain words blast radius, and the name of a strictly lower
risk substitute where one exists. `build_registry` refuses to construct
a registry with a substitute that is missing, self referential, or not
actually lower risk, so a broken declaration fails at import.

**Disagreement is escalated, not averaged.** The aggregator tracks which
workers support each hypothesis and which contradict it. A hypothesis
with confident voices on both sides is contested, and any action
addressing a contested hypothesis has its effective risk raised one
level. A low risk restart that would normally run unattended stops and
asks, because the system is no longer sure it is the right thing to do.
Uncertainty about the diagnosis and danger in the fix are different
things with the same remedy.

**The deadline is the product.** `tick` fires deadlines and applies the
rule's declared `on_expiry`: ladder to the next tier, run the safer
substitute, drop the action, or freeze the incident. Nothing sleeps and
nothing runs on a background thread, so every deadline is tested at its
exact boundary.

Policy is data, in [config/policy.yaml](config/policy.yaml):

```
risk        approval  deadline  on expiry       quorum  ladder
read_only   no        -         deny            1       -
low         no        -         deny            1       -
medium      yes       300s      escalate        1       primary -> secondary
high        yes       180s      safe_fallback   1       primary -> secondary -> incident_commander
critical    yes       600s      hold            2       incident_commander -> engineering_manager -> director
```

Four refusals happen at load time rather than during an incident: a rule
that requires approval without stating `on_expiry`, a quorum larger than
its own ladder, a tier in a ladder that no responder stands on, and a
`safe_fallback` that does not check out.

## Limitations, stated plainly

**The cluster is simulated.** `handoff/tools/world.py` is a dataclass.
Nothing in this repository has ever talked to Kubernetes, a database, or
a pager. Tool effects are real state changes to that dataclass, which is
what makes the demo show before and after rather than printed strings,
and it is not the same thing as working.

**The workers are rules, not models.** Five deterministic workers with
hand written thresholds. No LLM is called anywhere. The orchestration,
the escalation policy and the audit trail are the parts being built;
swapping a worker for an LLM backed one means implementing `Worker`,
which is a `name`, a `capabilities` set and a `handle` method. Whether
the escalation layer holds up when the workers are non deterministic is
an open question and this repository does not answer it.

**There is no scheduler.** `tick` is driven by the caller, which here is
the CLI and the scenario runner. A deployment needs something to call it
on a timer. That is deliberate, for the reason in
[ADR 0003](docs/adr/0003-escalation-is-a-policy.md), and it is also
genuinely missing.

**There is no notification channel.** `Journal.subscribe` is where a
pager would attach. Nothing attaches to it.

**The roster is static.** Seven people in a YAML file. No rotation
schedule, no timezones, no handover.

## Numbers

Every figure here comes from a command in this repository, run on the
simulated cluster with rule based workers. None of it is a claim about
production behaviour.

| | |
|---|---|
| tests | 200, all passing |
| scenarios | 11, all passing |
| suite wall time | 0.08s to 0.10s over three runs |
| source | 3666 lines across 35 modules |
| tests | 1726 lines |
| tools | 15, across five risk levels |
| third party dependencies | 0 |

Reproduce:

```bash
python3 -m unittest discover -s tests
python3 -m handoff.cli scenarios --dir evals/scenarios
```

## Three bugs worth keeping

The commit history keeps these rather than squashing them, because each
one is a category of mistake this kind of system invites.

**Safety code that could not run.** The supervisor raised the effective
risk of a contested action, but the planner was only fed confirmed
hypotheses, so a contested diagnosis produced no proposal and the risk
raising branch was unreachable through the normal flow. It read like a
guarantee and was decoration.

**A bump that was thrown away.** Having decided to escalate a contested
action at medium, the engine looked the rule up by the tool's declared
low risk. The low rule has an empty ladder, so the escalation exhausted
with zero attempts and the action was dropped. In the journal that reads
like a policy decision.

**A parser that quietly flattened config.** Nested maps inside list items
lost their nesting, so `modified_args` in a scenario came back empty and
an edited approval became an approval with no edits. It surfaced only
because `Decision.MODIFY` rejects missing arguments.

## Decisions

- [ADR 0001](docs/adr/0001-explicit-state-machines.md) explicit state machines rather than an agent framework
- [ADR 0002](docs/adr/0002-dependency-free-core.md) the core carries no third party dependencies
- [ADR 0003](docs/adr/0003-escalation-is-a-policy.md) escalation is a policy, not a callback
- [ADR 0004](docs/adr/0004-no-allow-on-expiry.md) there is no ALLOW on expiry

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) has the diagram and the
layer boundaries.

## License

MIT
