"""Running scenarios and reporting what did not match.

A scenario runs the real system against a described world, applies the
decisions and clock advances the file specifies, and then checks the
expectations. A failure names the expectation and what actually
happened, because a scenario report that only says "failed" is a report
somebody will stop reading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from handoff.core.clock import ManualClock
from handoff.core.types import Decision
from handoff.evalsvc.scenario import Scenario, parse
from handoff.system import build


@dataclass
class ScenarioResult:
    scenario: Scenario
    passed: bool
    failures: list[str] = field(default_factory=list)
    executed: list[str] = field(default_factory=list)
    end_state: str = ""
    report: str = ""

    @property
    def name(self) -> str:
        return self.scenario.name


@dataclass
class ScenarioReport:
    results: list[ScenarioResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "failures": r.failures,
                    "executed": r.executed,
                    "end_state": r.end_state,
                    "why_this_case_exists": r.scenario.why_this_case_exists,
                }
                for r in self.results
            ],
        }

    def render(self) -> str:
        lines = ["scenario results", "=" * 72]
        for result in self.results:
            mark = "pass" if result.passed else "FAIL"
            lines.append(f"[{mark}] {result.name}")
            lines.append(f"       why: {result.scenario.why_this_case_exists}")
            lines.append(f"       end state: {result.end_state}")
            lines.append(f"       executed: {', '.join(result.executed) or 'nothing'}")
            for failure in result.failures:
                lines.append(f"       -> {failure}")
        lines.append("=" * 72)
        lines.append(f"{self.passed} passed, {self.failed} failed")
        return "\n".join(lines)


def run_scenario(scenario: Scenario) -> ScenarioResult:
    clock = ManualClock()
    system = build(
        clock=clock,
        world=scenario.build_world(),
        autonomy=scenario.autonomy,
        seed=7,
    )
    run = system.supervisor.open(scenario.build_incident())
    system.supervisor.advance(run)

    decisions = list(scenario.decisions)
    advances = list(scenario.advance_seconds)
    guard = 0
    while (decisions or advances) and guard < 50:
        guard += 1
        if decisions and run.blocked_on is not None:
            spec = decisions.pop(0)
            escalation = system.engine.get(run.blocked_on)
            system.engine.decide(
                escalation.id,
                spec.get("by") or escalation.assignee,
                Decision(spec["decision"]),
                note=spec.get("note", ""),
                modified_args=spec.get("modified_args"),
            )
        elif advances:
            clock.advance(seconds=advances.pop(0))
            system.engine.tick()
        else:
            break
        system.supervisor.advance(run)

    executed = [a.tool for a in run.executed if a.ok]
    escalated = [system.engine.get(i).tool for i in run.escalation_ids]
    substituted = [a.tool for a in run.executed if a.substituted_for]
    expect = scenario.expect
    failures: list[str] = []

    if expect.end_state and str(run.state) != expect.end_state:
        failures.append(f"expected end state {expect.end_state}, got {run.state}")
    for tool in expect.executed:
        if tool not in executed:
            failures.append(f"expected {tool} to run, it did not. ran: {executed or 'nothing'}")
    for tool in expect.not_executed:
        if tool in executed:
            failures.append(f"expected {tool} NOT to run, it did")
    for tool in expect.escalated:
        if tool not in escalated:
            failures.append(f"expected {tool} to be escalated, escalated: {escalated or 'none'}")
    for tool in expect.substituted:
        if tool not in substituted:
            failures.append(f"expected {tool} to run as a substitution, it did not")
    confirmed = run.aggregate.confirmed()
    for name in expect.confirmed:
        if name not in confirmed:
            failures.append(f"expected {name} confirmed, confirmed: {confirmed}")
    contested = [v.name for v in run.aggregate.contested()]
    for name in expect.contested:
        if name not in contested:
            failures.append(f"expected {name} contested, contested: {contested}")
    rejected = run.aggregate.rejected()
    for name in expect.rejected:
        if name not in rejected:
            failures.append(f"expected {name} rejected, rejected: {rejected}")

    return ScenarioResult(
        scenario=scenario,
        passed=not failures,
        failures=failures,
        executed=executed,
        end_state=str(run.state),
        report=run.report(),
    )


def run_directory(directory: str | Path) -> ScenarioReport:
    paths = sorted(Path(directory).glob("*.yaml"))
    return ScenarioReport(results=[run_scenario(parse(p)) for p in paths])
