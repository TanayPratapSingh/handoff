"""The append only journal.

Three properties are load bearing:

append only      nothing is edited or removed, so the record of what the
                 system decided cannot drift from what it did
write then act   the caller records intent before applying the effect
replayable       an incident's state can be rebuilt from its events alone

The journal is the thing you hand to the person who asks why the system
restarted their database at 3am. Everything else in this repository is in
service of that answer being complete.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path

from handoff.bus.events import Event, EventKind


class Journal:
    def __init__(self, sink: Path | None = None) -> None:
        self._events: list[Event] = []
        self._subscribers: list[Callable[[Event], None]] = []
        self._sink = sink
        if sink is not None:
            sink.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: Event) -> Event:
        self._events.append(event)
        if self._sink is not None:
            with self._sink.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        for subscriber in self._subscribers:
            subscriber(event)
        return event

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        """Register a side channel, for example a pager or a live console.

        Subscribers run after the event is durable. A subscriber that raises
        is a bug in the subscriber and is allowed to propagate, because a
        pager that silently fails is the same as no pager.
        """
        self._subscribers.append(fn)

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self._events)

    def all(self) -> list[Event]:
        return list(self._events)

    def for_incident(self, incident_id: str) -> list[Event]:
        return [e for e in self._events if e.incident_id == incident_id]

    def of_kind(self, *kinds: EventKind) -> list[Event]:
        wanted = set(kinds)
        return [e for e in self._events if e.kind in wanted]

    def count(self, kind: EventKind) -> int:
        return sum(1 for e in self._events if e.kind == kind)

    def last(self, kind: EventKind | None = None) -> Event | None:
        for event in reversed(self._events):
            if kind is None or event.kind == kind:
                return event
        return None

    def timeline(self, incident_id: str | None = None) -> str:
        events = self.for_incident(incident_id) if incident_id else self._events
        return "\n".join(e.summary() for e in events)
