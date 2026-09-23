"""Who is available to answer an escalation.

A roster is not a list of names. It is a list of names with three things
attached that determine whether paging that person is useful:

tier            where they sit on the ladder
skills          what they are competent to approve
load            how many open escalations they already hold

The third one is the one that gets skipped, and skipping it is how a
system pages the same exhausted person nine times during one incident
while four other responders sit idle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from handoff.core.errors import ConfigError
from handoff.core.miniyaml import load


@dataclass
class Responder:
    id: str
    name: str
    tier: str
    skills: frozenset[str] = frozenset()
    available: bool = True
    max_concurrent: int = 2
    open_count: int = 0

    @property
    def has_capacity(self) -> bool:
        return self.available and self.open_count < self.max_concurrent

    def can_approve(self, skill: str | None) -> bool:
        return skill is None or skill in self.skills


@dataclass
class Roster:
    responders: dict[str, Responder] = field(default_factory=dict)
    tiers: tuple[str, ...] = ()

    def add(self, responder: Responder) -> Responder:
        if responder.id in self.responders:
            raise ConfigError(f"duplicate responder id: {responder.id}")
        if self.tiers and responder.tier not in self.tiers:
            raise ConfigError(
                f"responder {responder.id} is on unknown tier {responder.tier!r}, "
                f"known tiers are {list(self.tiers)}"
            )
        self.responders[responder.id] = responder
        return responder

    def get(self, responder_id: str) -> Responder:
        if responder_id not in self.responders:
            raise ConfigError(f"no such responder: {responder_id}")
        return self.responders[responder_id]

    def on_tier(self, tier: str) -> list[Responder]:
        return [r for r in self.responders.values() if r.tier == tier]

    def candidates(self, tier: str, skill: str | None = None) -> list[Responder]:
        """Everyone on this tier who could actually take the page.

        Sorted by current load so that an even spread is the default and
        the ordering is deterministic.
        """
        pool = [
            r for r in self.on_tier(tier)
            if r.has_capacity and r.can_approve(skill)
        ]
        return sorted(pool, key=lambda r: (r.open_count, r.id))

    def acquire(self, responder_id: str) -> Responder:
        r = self.get(responder_id)
        r.open_count += 1
        return r

    def release(self, responder_id: str) -> Responder:
        r = self.get(responder_id)
        r.open_count = max(0, r.open_count - 1)
        return r

    def set_available(self, responder_id: str, available: bool) -> Responder:
        r = self.get(responder_id)
        r.available = available
        return r

    @classmethod
    def from_config(cls, path: str | Path) -> Roster:
        doc = load(path)
        if not isinstance(doc, dict):
            raise ConfigError(f"{path}: expected a mapping at the top level")
        tiers = tuple(doc.get("tiers") or ())
        if not tiers:
            raise ConfigError(f"{path}: 'tiers' is required and must be a non empty list")
        roster = cls(tiers=tiers)
        for entry in doc.get("responders") or []:
            missing = [k for k in ("id", "name", "tier") if k not in entry]
            if missing:
                raise ConfigError(f"{path}: responder missing {missing}: {entry}")
            roster.add(Responder(
                id=entry["id"],
                name=entry["name"],
                tier=entry["tier"],
                skills=frozenset(entry.get("skills") or ()),
                available=entry.get("available", True),
                max_concurrent=entry.get("max_concurrent", 2),
            ))
        empty = [t for t in tiers if not roster.on_tier(t)]
        if empty:
            raise ConfigError(f"{path}: tiers with no responders: {empty}")
        return roster
