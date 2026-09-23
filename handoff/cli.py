"""Command line entry point.

    python3 -m handoff.cli demo
    python3 -m handoff.cli policy
    python3 -m handoff.cli roster
    python3 -m handoff.cli scenarios --dir evals/scenarios

The demo runs on a ManualClock so that the output is identical on every
run. Nothing here sleeps and nothing here reaches the network.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from handoff.core.clock import ManualClock
from handoff.core.types import Autonomy, Decision, Severity
from handoff.escalation.policy import Policy
from handoff.escalation.roster import Roster
from handoff.supervisor.incident import Incident
from handoff.system import CONFIG_DIR, build
from handoff.tools.world import Service, World

RULE = "=" * 72
THIN = "-" * 72


def _heading(text: str) -> None:
    print(f"\n{RULE}\n{text}\n{RULE}")


def _section(text: str) -> None:
    print(f"\n{THIN}\n{text}\n{THIN}")


def cmd_policy(args: argparse.Namespace) -> int:
    policy = Policy.from_config(args.policy or CONFIG_DIR / "policy.yaml")
    _heading(f"policy  autonomy={policy.autonomy}  "
             f"escalate at or above {policy.escalate_at_or_above}")
    header = f"{'risk':<12}{'approval':<10}{'deadline':<10}{'on expiry':<16}{'quorum':<8}ladder"
    print(header)
    print(THIN)
    for risk in sorted(policy.rules, key=lambda r: r.rank):
        rule = policy.rules[risk]
        approval = "yes" if rule.requires_approval else "no"
        deadline = f"{rule.deadline_seconds}s" if rule.deadline_seconds else "-"
        print(
            f"{str(risk):<12}{approval:<10}{deadline:<10}"
            f"{str(rule.on_expiry):<16}{rule.quorum:<8}{' -> '.join(rule.ladder) or '-'}"
        )
    return 0


def cmd_roster(args: argparse.Namespace) -> int:
    roster = Roster.from_config(args.roster or CONFIG_DIR / "roster.yaml")
    _heading("on call roster")
    for tier in roster.tiers:
        print(f"\n{tier}")
        for responder in roster.on_tier(tier):
            state = "available" if responder.available else "unavailable"
            print(
                f"  {responder.id:<8}{responder.name:<20}{state:<14}"
                f"max {responder.max_concurrent}  skills: "
                f"{', '.join(sorted(responder.skills)) or 'none'}"
            )
    return 0


def _act_one() -> None:
    _heading("ACT 1  guarded autonomy: act on the cheap things, stop at the rest")
    clock = ManualClock()
    system = build(clock=clock, world=World.sample(), seed=7)
    run = system.supervisor.open(Incident(
        title="Checkout p99 latency spike",
        service="checkout",
        symptom="latency and errors after deploy",
        severity=Severity.SEV2,
    ))
    system.supervisor.advance(run)

    print(f"\n{run.incident.describe()}")
    _section("what the workers found")
    print(run.aggregate.summary())

    _section("what the supervisor did on its own")
    for action in run.executed:
        print(f"  ran {action.tool}({action.args})")

    escalation = system.engine.get(run.blocked_on)
    _section("where it stopped")
    print(f"  state      {run.state}")
    print(f"  asking     {escalation.tool}({escalation.args})")
    print(f"  risk       {escalation.risk}")
    print(f"  blast      {escalation.blast_radius}")
    print(f"  paged      {escalation.assignee} on tier {escalation.current_tier}")
    print(f"  deadline   {escalation.deadline_seconds}s, then {escalation.on_expiry}")

    system.engine.decide(
        escalation.id, escalation.assignee, Decision.APPROVE,
        note="peak has passed, capacity is fine",
    )
    system.supervisor.advance(run)

    _section("after the human approved")
    print(run.report())


def _act_two() -> None:
    _heading("ACT 2  nobody answers: the deadline decides, and it is written down")
    clock = ManualClock()
    system = build(clock=clock, world=World.sample(), seed=7)
    run = system.supervisor.open(Incident(
        title="Orders database replication lag",
        service="checkout",
        symptom="replication lag climbing",
        severity=Severity.SEV1,
    ))
    system.world.database.replication_lag_s = 42.0
    system.supervisor.advance(run)

    escalation = system.engine.get(run.blocked_on)
    print(f"\n  raised     {escalation.tool} at risk {escalation.risk}")
    print(f"  ladder     {' -> '.join(escalation.ladder)}")
    print(f"  on expiry  {escalation.on_expiry}")
    print(f"\n  nobody answers. advancing the clock instead of waiting.\n")

    for _ in range(5):
        if not system.engine.open():
            break
        clock.advance(seconds=400)
        for fired in system.engine.tick():
            attempt = fired.attempts[-1]
            who = attempt.responder_id or "nobody available"
            print(f"  t+{int((clock.now() - ManualClock.EPOCH).total_seconds()):>5}s  "
                  f"timeout, now {fired.state} at {attempt.tier}/{who}")
    system.supervisor.advance(run)

    _section("audit trail for that escalation")
    print(escalation.audit())

    _section("outcome")
    print(run.report())


def _act_three() -> None:
    _heading("ACT 3  the workers disagree, so a low risk action buys a review")
    clock = ManualClock()
    world = World(services={
        "checkout": Service("checkout", replicas=6, error_rate=0.25,
                            latency_p99_ms=300, healthy=True),
    })
    system = build(clock=clock, world=world, seed=7)
    run = system.supervisor.open(Incident(
        title="Checkout errors up, latency flat",
        service="checkout",
        symptom="errors without latency",
        severity=Severity.SEV3,
    ))
    system.supervisor.advance(run)

    _section("the disagreement")
    print(run.aggregate.summary())

    escalation = system.engine.get(run.blocked_on)
    tool = system.supervisor.tools.get(escalation.tool)
    _section("what it did about it")
    print(f"  action           {escalation.tool}")
    print(f"  declared risk    {tool.risk}")
    print(f"  effective risk   {escalation.risk}")
    print(f"  reason given     {escalation.reason}")
    print(f"  paged            {escalation.assignee}")
    print(
        "\n  Nothing about restarting a service got more dangerous. The system\n"
        "  stopped being sure it was the right thing to do, and that is the\n"
        "  same problem with the same answer."
    )


def cmd_demo(args: argparse.Namespace) -> int:
    _act_one()
    _act_two()
    _act_three()
    _heading("done")
    print(
        "Every number above came from a deterministic simulation with rule\n"
        "based workers and a fake cluster. No model was called and nothing\n"
        "touched a network. See the limitations section of the README.\n"
    )
    return 0


def cmd_scenarios(args: argparse.Namespace) -> int:
    from handoff.evalsvc import run_directory

    report = run_directory(Path(args.dir))
    print(report.render())
    if args.json:
        Path(args.json).write_text(json.dumps(report.to_dict(), indent=2))
        print(f"\nwrote {args.json}")
    return 0 if report.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="handoff", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run the three act demonstration")
    demo.set_defaults(fn=cmd_demo)

    policy = sub.add_parser("policy", help="print the escalation policy table")
    policy.add_argument("--policy", help="path to policy.yaml")
    policy.set_defaults(fn=cmd_policy)

    roster = sub.add_parser("roster", help="print the on call roster")
    roster.add_argument("--roster", help="path to roster.yaml")
    roster.set_defaults(fn=cmd_roster)

    scenarios = sub.add_parser("scenarios", help="run the scenario suite")
    scenarios.add_argument("--dir", default="evals/scenarios")
    scenarios.add_argument("--json", help="also write the report as json")
    scenarios.set_defaults(fn=cmd_scenarios)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
