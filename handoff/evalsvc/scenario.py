"""Parsing a scenario file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from handoff.core.errors import ConfigError
from handoff.core.miniyaml import load
from handoff.core.types import Autonomy, Severity
from handoff.tools.world import Service, World


@dataclass(frozen=True)
class Expectation:
    end_state: str | None = None
    executed: tuple[str, ...] = ()
    not_executed: tuple[str, ...] = ()
    escalated: tuple[str, ...] = ()
    substituted: tuple[str, ...] = ()
    confirmed: tuple[str, ...] = ()
    contested: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    name: str
    why_this_case_exists: str
    incident: dict[str, Any]
    expect: Expectation
    services: tuple[dict[str, Any], ...] = ()
    database: dict[str, Any] = field(default_factory=dict)
    autonomy: Autonomy = Autonomy.GUARDED
    decisions: tuple[dict[str, Any], ...] = ()
    advance_seconds: tuple[int, ...] = ()
    path: Path | None = None

    def build_world(self) -> World:
        world = World()
        for spec in self.services:
            world.services[spec["name"]] = Service(
                name=spec["name"],
                replicas=spec.get("replicas", 3),
                healthy=spec.get("healthy", True),
                version=spec.get("version", "v1.4.2"),
                error_rate=float(spec.get("error_rate", 0.01)),
                latency_p99_ms=spec.get("latency_p99_ms", 180),
            )
        for key, value in self.database.items():
            if not hasattr(world.database, key):
                raise ConfigError(f"{self.name}: database has no field {key!r}")
            setattr(world.database, key, value)
        return world

    def build_incident(self):
        from handoff.supervisor.incident import Incident

        missing = [k for k in ("title", "service", "symptom") if k not in self.incident]
        if missing:
            raise ConfigError(f"{self.name}: incident missing {missing}")
        return Incident(
            title=self.incident["title"],
            service=self.incident["service"],
            symptom=self.incident["symptom"],
            severity=Severity(self.incident.get("severity", "sev2")),
        )


def _tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def parse(path: str | Path) -> Scenario:
    p = Path(path)
    doc = load(p)
    if not isinstance(doc, dict):
        raise ConfigError(f"{p}: expected a mapping at the top level")
    for required in ("name", "why_this_case_exists", "incident", "expect"):
        if required not in doc:
            raise ConfigError(f"{p}: missing required key {required!r}")
    expect = doc["expect"] or {}
    return Scenario(
        name=doc["name"],
        why_this_case_exists=doc["why_this_case_exists"],
        incident=doc["incident"],
        expect=Expectation(
            end_state=expect.get("end_state"),
            executed=_tuple(expect.get("executed")),
            not_executed=_tuple(expect.get("not_executed")),
            escalated=_tuple(expect.get("escalated")),
            substituted=_tuple(expect.get("substituted")),
            confirmed=_tuple(expect.get("confirmed")),
            contested=_tuple(expect.get("contested")),
            rejected=_tuple(expect.get("rejected")),
        ),
        services=tuple(doc.get("services") or ()),
        database=doc.get("database") or {},
        autonomy=Autonomy(doc.get("autonomy", "guarded")),
        decisions=tuple(doc.get("decisions") or ()),
        advance_seconds=tuple(doc.get("advance_seconds") or ()),
        path=p,
    )
