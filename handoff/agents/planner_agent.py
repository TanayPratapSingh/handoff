"""The runbook retriever and the remediation planner.

The planner is the only worker that produces proposals, and it produces
them from the findings the analysts returned plus a runbook. It attaches
the hypothesis each proposal addresses so that a proposal whose
supporting hypothesis turns out to be contested can be traced back.

It deliberately proposes the cheapest adequate action first. The ordering
is not an optimisation, it is a safety property: if the supervisor stops
after the first success, then proposing restart before failover means the
system tries the reversible thing first.
"""

from __future__ import annotations

from handoff.agents.base import (
    Finding,
    ProposedAction,
    Subtask,
    WorkerContext,
    WorkerResult,
)


class RunbookRetriever:
    name = "runbook_retriever"
    capabilities = frozenset({"runbook"})

    def handle(self, subtask: Subtask, ctx: WorkerContext) -> WorkerResult:
        symptom = subtask.args.get("symptom", "")
        out = ctx.call("search_runbooks", symptom=symptom)
        if out["runbook"] is None:
            return WorkerResult(
                subtask.id,
                self.name,
                findings=[
                    Finding(
                        source=self.name,
                        claim=f"no runbook matches {symptom!r}",
                        confidence=0.99,
                        evidence=out,
                    )
                ],
            )
        return WorkerResult(
            subtask.id,
            self.name,
            findings=[
                Finding(
                    source=self.name,
                    claim=f"runbook {out['runbook']} applies: {out['title']}",
                    confidence=0.85,
                    evidence=out,
                )
            ],
        )


class RemediationPlanner:
    name = "remediation_planner"
    capabilities = frozenset({"remediation"})

    def handle(self, subtask: Subtask, ctx: WorkerContext) -> WorkerResult:
        service = subtask.args.get("service", "")
        hypotheses = set(subtask.args.get("hypotheses") or ())
        proposals: list[ProposedAction] = []

        if "capacity_shortfall" in hypotheses and service:
            current = ctx.call("read_metrics", service=service)["replicas"]
            proposals.append(
                ProposedAction(
                    tool="scale_deployment",
                    args={"service": service, "replicas": min(current * 2, 200)},
                    reason=f"{service} is saturated at {current} replicas",
                    proposed_by=self.name,
                    addresses="capacity_shortfall",
                )
            )

        if "service_degraded" in hypotheses and service:
            proposals.append(
                ProposedAction(
                    tool="restart_service",
                    args={"service": service},
                    reason=f"{service} is degraded and a roll restart is reversible",
                    proposed_by=self.name,
                    addresses="service_degraded",
                )
            )

        if "database_fault" in hypotheses:
            replication = ctx.call("read_replication")
            target = replication["replicas"][0] if replication["replicas"] else None
            if target:
                proposals.append(
                    ProposedAction(
                        tool="failover_database",
                        args={"target": target},
                        reason=(
                            f"replication lag {replication['replication_lag_s']}s on "
                            f"{replication['primary']}"
                        ),
                        proposed_by=self.name,
                        addresses="database_fault",
                    )
                )

        if "upstream_fault" in hypotheses:
            proposals.append(
                ProposedAction(
                    tool="page_vendor",
                    args={"vendor": "payments-upstream"},
                    reason="the dominant error names an upstream dependency",
                    proposed_by=self.name,
                    addresses="upstream_fault",
                )
            )

        proposals.sort(key=lambda p: _RISK_ORDER.get(p.tool, 99))

        findings = [
            Finding(
                source=self.name,
                claim=f"{len(proposals)} remediation options for {sorted(hypotheses)}",
                confidence=0.7,
                evidence={"hypotheses": sorted(hypotheses)},
            )
        ]
        return WorkerResult(subtask.id, self.name, findings=findings, proposals=proposals)


# Cheapest adequate action first. Reversible before irreversible, narrow
# blast radius before wide. The supervisor stops after the first proposal
# that resolves the incident, so this ordering decides what gets tried.
_RISK_ORDER = {
    "page_vendor": 0,
    "purge_cache": 1,
    "restart_service": 2,
    "scale_deployment": 3,
    "rollback_release": 4,
    "enable_read_only": 5,
    "drain_node": 6,
    "failover_database": 7,
    "force_terminate": 8,
    "delete_volume": 9,
}
