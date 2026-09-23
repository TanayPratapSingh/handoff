"""The built in tool set for the incident domain.

Organised by what the tool can break, because that is the axis the
escalation layer cares about:

register_readonly     changes nothing, callable at any autonomy level
register_mutating     changes running state, reversible, low to medium risk
register_destructive  high or critical, some of it irreversible
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


# Mutating tools. These change running state. All of them are reversible in
# the sense that a competent operator can undo them, which is the line
# between this group and the destructive group below.


def _restart_service(world: World, args: dict[str, Any]) -> dict[str, Any]:
    svc = world.service(args["service"])
    svc.restarts += 1
    svc.healthy = True
    svc.error_rate = round(svc.error_rate * 0.4, 4)
    svc.latency_p99_ms = int(svc.latency_p99_ms * 0.5)
    return {"service": svc.name, "restarts": svc.restarts, "healthy": svc.healthy}


def _scale_deployment(world: World, args: dict[str, Any]) -> dict[str, Any]:
    svc = world.service(args["service"])
    before = svc.replicas
    svc.replicas = args["replicas"]
    if svc.replicas > before:
        svc.latency_p99_ms = int(svc.latency_p99_ms * before / max(svc.replicas, 1))
    return {"service": svc.name, "replicas_before": before, "replicas_after": svc.replicas}


def _purge_cache(world: World, args: dict[str, Any]) -> dict[str, Any]:
    world.cache_purges += 1
    return {"namespace": args["namespace"], "purges": world.cache_purges}


def _rollback_release(world: World, args: dict[str, Any]) -> dict[str, Any]:
    svc = world.service(args["service"])
    rolled_from = svc.version
    svc.version, svc.previous_version = svc.previous_version, svc.version
    svc.error_rate = round(svc.error_rate * 0.2, 4)
    svc.healthy = True
    return {"service": svc.name, "from": rolled_from, "to": svc.version}


def _drain_node(world: World, args: dict[str, Any]) -> dict[str, Any]:
    node = args["node"]
    if node not in world.drained_nodes:
        world.drained_nodes.append(node)
    return {"node": node, "drained": sorted(world.drained_nodes)}


def _enable_read_only(world: World, args: dict[str, Any]) -> dict[str, Any]:
    world.database.read_only = True
    return {"database": world.database.name, "read_only": True}


def _page_vendor(world: World, args: dict[str, Any]) -> dict[str, Any]:
    world.vendor_paged.append(args["vendor"])
    return {"vendor": args["vendor"], "paged": len(world.vendor_paged)}


def register_mutating(registry: ToolRegistry) -> ToolRegistry:
    registry.register(Tool(
        name="restart_service",
        description="Roll restart every pod of a service",
        risk=Risk.LOW,
        fields=(SERVICE,),
        run=_restart_service,
        blast_radius="one service, brief connection resets during the roll",
    ))
    registry.register(Tool(
        name="purge_cache",
        description="Purge a cache namespace",
        risk=Risk.LOW,
        fields=(Field("namespace", str),),
        run=_purge_cache,
        blast_radius="cold cache and a latency spike until it refills",
    ))
    registry.register(Tool(
        name="page_vendor",
        description="Page an upstream vendor on call",
        risk=Risk.LOW,
        fields=(Field("vendor", str),),
        run=_page_vendor,
        blast_radius="none technically, wakes somebody at another company",
    ))
    registry.register(Tool(
        name="scale_deployment",
        description="Change the replica count of a service",
        risk=Risk.MEDIUM,
        fields=(SERVICE, Field("replicas", int, minimum=0, maximum=200)),
        run=_scale_deployment,
        blast_radius="cluster capacity and cost, scaling to zero takes the service down",
    ))
    registry.register(Tool(
        name="rollback_release",
        description="Roll a service back to its previous version",
        risk=Risk.MEDIUM,
        fields=(SERVICE,),
        run=_rollback_release,
        blast_radius="one service reverts, in flight schema assumptions may break",
    ))
    registry.register(Tool(
        name="drain_node",
        description="Cordon and drain a node",
        risk=Risk.MEDIUM,
        fields=(Field("node", str),),
        run=_drain_node,
        blast_radius="workloads reschedule, capacity drops until replaced",
    ))
    registry.register(Tool(
        name="enable_read_only",
        description="Put the orders database into read only mode",
        risk=Risk.MEDIUM,
        run=_enable_read_only,
        blast_radius="writes rejected, checkout degrades but data is safe",
    ))
    return registry


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_readonly(registry)
    register_mutating(registry)
    return registry
