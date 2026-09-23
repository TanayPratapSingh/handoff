"""The read only analyst workers.

Three workers that look at the incident and report what they see. None of
them proposes an action; that is the remediation planner's job, and
keeping the split means a disagreement between analysts surfaces before
anybody has proposed doing anything about it.

These are deterministic rule based analysts, not models. Swapping one for
an LLM backed worker means implementing the same Worker protocol. The
README says which parts of the reported behaviour come from rules, and
that distinction is the whole reason the split is documented here.
"""

from __future__ import annotations

from handoff.agents.base import Finding, Subtask, WorkerContext, WorkerResult


class LogAnalyst:
    name = "log_analyst"
    capabilities = frozenset({"logs"})

    def handle(self, subtask: Subtask, ctx: WorkerContext) -> WorkerResult:
        service = subtask.args.get("service")
        if not service:
            return WorkerResult.failed(subtask.id, self.name, "no service in subtask args")
        out = ctx.call("read_logs", service=service, window_minutes=15)
        findings = [Finding(
            source=self.name,
            claim=f"{service} logged {out['error_lines']} error lines in 15 minutes",
            confidence=0.9,
            evidence=out,
            supports=("service_degraded",) if out["error_lines"] > 50 else (),
            contradicts=() if out["error_lines"] > 50 else ("service_degraded",),
        )]
        if out["top_error"] != "none":
            findings.append(Finding(
                source=self.name,
                claim=f"dominant error is: {out['top_error']}",
                confidence=0.75,
                evidence={"top_error": out["top_error"]},
                supports=("upstream_fault",) if "upstream" in out["top_error"] else (),
            ))
        return WorkerResult(subtask.id, self.name, findings=findings)


class MetricsAnalyst:
    name = "metrics_analyst"
    capabilities = frozenset({"metrics"})

    def handle(self, subtask: Subtask, ctx: WorkerContext) -> WorkerResult:
        service = subtask.args.get("service")
        if not service:
            return WorkerResult.failed(subtask.id, self.name, "no service in subtask args")
        out = ctx.call("read_metrics", service=service)
        findings = [Finding(
            source=self.name,
            claim=(
                f"{service} p99 latency is {out['latency_p99_ms']}ms "
                f"at {out['replicas']} replicas"
            ),
            confidence=0.95,
            evidence=out,
            supports=("service_degraded",) if out["saturated"] else (),
            contradicts=() if out["saturated"] else ("service_degraded",),
        )]
        if out["saturated"] and out["replicas"] < 8:
            findings.append(Finding(
                source=self.name,
                claim=f"{service} looks under provisioned for current load",
                confidence=0.6,
                evidence={"replicas": out["replicas"]},
                supports=("capacity_shortfall",),
            ))
        return WorkerResult(subtask.id, self.name, findings=findings)


class ReplicationAnalyst:
    name = "replication_analyst"
    capabilities = frozenset({"replication"})

    LAG_THRESHOLD_S = 5.0

    def handle(self, subtask: Subtask, ctx: WorkerContext) -> WorkerResult:
        out = ctx.call("read_replication")
        lagging = out["replication_lag_s"] > self.LAG_THRESHOLD_S
        findings = [Finding(
            source=self.name,
            claim=(
                f"{out['database']} replication lag is {out['replication_lag_s']}s "
                f"against a {self.LAG_THRESHOLD_S}s threshold"
            ),
            confidence=0.95,
            evidence=out,
            supports=("database_fault",) if lagging else (),
            contradicts=() if lagging else ("database_fault",),
        )]
        return WorkerResult(subtask.id, self.name, findings=findings)
