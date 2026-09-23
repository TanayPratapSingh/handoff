"""A simulated cluster for the tools to act on.

This is not a mock in the test double sense. It is a small state machine
standing in for infrastructure, so that tool effects are observable and the
demo shows real before and after state rather than printed strings.

It is also, obviously, not a cluster. Nothing here talks to anything. The
README says so in the limitations section and so does this docstring,
because the difference between a simulation and a deployment is the single
most over claimed thing in portfolio projects.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Service:
    name: str
    replicas: int = 3
    healthy: bool = True
    restarts: int = 0
    version: str = "v1.4.2"
    previous_version: str = "v1.4.1"
    error_rate: float = 0.01
    latency_p99_ms: int = 180


@dataclass
class Database:
    name: str = "orders-primary"
    primary: str = "node-a"
    replicas: tuple[str, ...] = ("node-b", "node-c")
    read_only: bool = False
    replication_lag_s: float = 0.4
    failovers: int = 0


@dataclass
class World:
    services: dict[str, Service] = field(default_factory=dict)
    database: Database = field(default_factory=Database)
    drained_nodes: list[str] = field(default_factory=list)
    deleted_volumes: list[str] = field(default_factory=list)
    snapshots: list[str] = field(default_factory=list)
    cache_purges: int = 0
    vendor_paged: list[str] = field(default_factory=list)

    @classmethod
    def sample(cls) -> World:
        return cls(
            services={
                "checkout": Service(
                    "checkout", replicas=6, error_rate=0.21, latency_p99_ms=2400, healthy=False
                ),
                "payments": Service("payments", replicas=4),
                "search": Service("search", replicas=2, latency_p99_ms=310),
            }
        )

    def service(self, name: str) -> Service:
        if name not in self.services:
            raise KeyError(f"no such service: {name}")
        return self.services[name]

    def snapshot(self) -> dict[str, object]:
        """A comparable view, for asserting what a run changed."""
        return {
            "services": {
                n: (s.replicas, s.healthy, s.restarts, s.version)
                for n, s in sorted(self.services.items())
            },
            "db": (self.database.primary, self.database.read_only, self.database.failovers),
            "drained": sorted(self.drained_nodes),
            "deleted_volumes": sorted(self.deleted_volumes),
            "snapshots": sorted(self.snapshots),
            "cache_purges": self.cache_purges,
        }
