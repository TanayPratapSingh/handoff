"""One call that wires the whole system together.

Everything is constructor injected, so a test can replace the clock, the
policy, the roster or the world without touching the rest. build() is
just the convenient default arrangement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from handoff.agents.analysts import LogAnalyst, MetricsAnalyst, ReplicationAnalyst
from handoff.agents.planner_agent import RemediationPlanner, RunbookRetriever
from handoff.agents.registry import WorkerRegistry
from handoff.bus.journal import Journal
from handoff.core.clock import Clock, SystemClock
from handoff.core.ids import IdGenerator
from handoff.core.types import Autonomy
from handoff.escalation.engine import EscalationEngine
from handoff.escalation.policy import Policy
from handoff.escalation.roster import Roster
from handoff.supervisor.supervisor import Supervisor
from handoff.tools.builtin import build_registry
from handoff.tools.world import World

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def default_workers() -> WorkerRegistry:
    registry = WorkerRegistry()
    for worker in (
        LogAnalyst(),
        MetricsAnalyst(),
        ReplicationAnalyst(),
        RunbookRetriever(),
        RemediationPlanner(),
    ):
        registry.register(worker)
    return registry


@dataclass
class System:
    supervisor: Supervisor
    engine: EscalationEngine
    journal: Journal
    roster: Roster
    policy: Policy
    world: World
    clock: Clock

    def tick(self):
        return self.engine.tick()


def build(
    clock: Clock | None = None,
    world: World | None = None,
    policy_path: str | Path | None = None,
    roster_path: str | Path | None = None,
    autonomy: Autonomy | None = None,
    journal_sink: Path | None = None,
    seed: int | None = None,
) -> System:
    clock = clock or SystemClock()
    world = world if world is not None else World.sample()
    policy = Policy.from_config(policy_path or CONFIG_DIR / "policy.yaml")
    if autonomy is not None:
        policy = policy.with_autonomy(autonomy)
    roster = Roster.from_config(roster_path or CONFIG_DIR / "roster.yaml")
    journal = Journal(sink=journal_sink)
    tools = build_registry()
    engine = EscalationEngine(
        policy=policy, roster=roster, journal=journal, clock=clock, registry=tools
    )
    supervisor = Supervisor(
        workers=default_workers(),
        tools=tools,
        engine=engine,
        journal=journal,
        clock=clock,
        world=world,
        ids=IdGenerator(seed),
    )
    return System(
        supervisor=supervisor, engine=engine, journal=journal,
        roster=roster, policy=policy, world=world, clock=clock,
    )
