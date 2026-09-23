"""Scenario based evaluation.

A scenario is a yaml file describing a world, an incident and what the
system is expected to do. It is a regression test for behaviour rather
than for code: the assertions are about which actions ran, which did
not, and what state the run ended in.

Scenarios exist because the interesting properties of this system are
sequences, not return values. "A high risk action that nobody approves
falls back to the safer tool" is not a unit of code, it is a path
through six components, and the only honest way to check it is to run
the path.
"""

from handoff.evalsvc.runner import ScenarioReport, ScenarioResult, run_directory, run_scenario

__all__ = ["ScenarioReport", "ScenarioResult", "run_directory", "run_scenario"]
