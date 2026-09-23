"""Decomposing an incident into subtasks.

The decomposition is deliberately static. A model could generate a plan
per incident, and a later version probably should, but a static plan
makes the rest of the system observable: the same incident always fans
out the same way, so a change in outcome is a change in the world or in
the policy, never in the plan.

Diagnosis fans out with no dependencies. Remediation depends on all of
it, because proposing an action before the analysts have reported is how
a system ends up proposing a database failover for a caching problem.
"""

from __future__ import annotations

from handoff.agents.base import Subtask
from handoff.core.ids import IdGenerator
from handoff.supervisor.incident import Incident

DIAGNOSTIC_CAPABILITIES = ("logs", "metrics", "replication", "runbook")


def plan(incident: Incident, ids: IdGenerator | None = None) -> list[Subtask]:
    ids = ids or IdGenerator()
    subtasks: list[Subtask] = []
    for capability in DIAGNOSTIC_CAPABILITIES:
        subtasks.append(
            Subtask(
                id=ids.subtask(),
                capability=capability,
                description=f"inspect {capability} for {incident.service}",
                args={"service": incident.service, "symptom": incident.symptom},
            )
        )
    subtasks.append(
        Subtask(
            id=ids.subtask(),
            capability="remediation",
            description=f"propose remediation for {incident.service}",
            args={"service": incident.service},
            depends_on=tuple(s.id for s in subtasks),
        )
    )
    return subtasks


def ready(subtasks: list[Subtask], done: set[str]) -> list[Subtask]:
    """Subtasks whose dependencies have all completed."""
    return [s for s in subtasks if s.id not in done and set(s.depends_on) <= done]
