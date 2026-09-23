"""The built in tool set for the incident domain.

Read only diagnostics first. These are the tools a worker may always call,
at any autonomy level, without asking anybody, because they change nothing.
"""

from __future__ import annotations

from typing import Any

from handoff.core.types import Risk
from handoff.tools.registry import Tool, ToolRegistry
from handoff.tools.schema import Field
from handoff.tools.world import World

SERVICE = Field("service", str, description="service name, for example checkout")


def _read_logs(world: World, args: dict[str, Any]) -> dict[str, Any]:
    svc = world.service(args["service"])
    window = args["window_minutes"]
    errors = int(svc.error_rate * 1000 * (window / 5))
    return {
        "service": svc.name,
        "window_minutes": window,
        "error_lines": errors,
        "top_error": "upstream timeout calling payments" if not svc.healthy else "none",
        "healthy": svc.healthy,
    }


def _read_metrics(world: World, args: dict[str, Any]) -> dict[str, Any]:
    svc = world.service(args["service"])
    return {
        "service": svc.name,
        "error_rate": svc.error_rate,
        "latency_p99_ms": svc.latency_p99_ms,
        "replicas": svc.replicas,
        "saturated": svc.latency_p99_ms > 1000,
    }


def _read_replication(world: World, args: dict[str, Any]) -> dict[str, Any]:
    db = world.database
    return {
        "database": db.name,
        "primary": db.primary,
        "replicas": list(db.replicas),
        "replication_lag_s": db.replication_lag_s,
        "read_only": db.read_only,
    }


def _search_runbooks(world: World, args: dict[str, Any]) -> dict[str, Any]:
    symptom = args["symptom"].lower()
    library = {
        "latency": ("RB-014", "Elevated p99 on a stateless service",
                    ["check replica count", "check upstream saturation", "scale out"]),
        "errors": ("RB-002", "Error rate spike after release",
                   ["compare to previous version", "roll back", "verify"]),
        "replication": ("RB-031", "Replication lag on the orders database",
                        ["confirm lag trend", "consider read only mode", "failover last"]),
    }
    for key, (rid, title, steps) in library.items():
        if key in symptom:
            return {"runbook": rid, "title": title, "steps": steps, "matched_on": key}
    return {"runbook": None, "title": None, "steps": [], "matched_on": None}


def register_readonly(registry: ToolRegistry) -> ToolRegistry:
    registry.register(Tool(
        name="read_logs",
        description="Read recent error logs for a service",
        risk=Risk.READ_ONLY,
        fields=(SERVICE, Field("window_minutes", int, required=False, default=15,
                               minimum=1, maximum=1440)),
        run=_read_logs,
        blast_radius="none, reads only",
    ))
    registry.register(Tool(
        name="read_metrics",
        description="Read error rate, latency and replica count for a service",
        risk=Risk.READ_ONLY,
        fields=(SERVICE,),
        run=_read_metrics,
        blast_radius="none, reads only",
    ))
    registry.register(Tool(
        name="read_replication",
        description="Read replication topology and lag for the orders database",
        risk=Risk.READ_ONLY,
        run=_read_replication,
        blast_radius="none, reads only",
    ))
    registry.register(Tool(
        name="search_runbooks",
        description="Find the runbook matching a symptom",
        risk=Risk.READ_ONLY,
        fields=(Field("symptom", str),),
        run=_search_runbooks,
        blast_radius="none, reads only",
    ))
    return registry


def build_registry() -> ToolRegistry:
    return register_readonly(ToolRegistry())
