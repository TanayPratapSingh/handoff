"""Time, injected.

Every deadline in this system is measured against a Clock passed in by the
caller. Nothing calls datetime.now() directly outside SystemClock, and
nothing sleeps. That is what makes the expiry tests deterministic instead of
slow and flaky: ManualClock advances by assignment.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current instant, timezone aware, in UTC."""
        ...


class SystemClock:
    """Wall clock. The only place datetime.now() is permitted."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock:
    """A clock the test drives by hand.

    Starts at a fixed epoch so that golden output is stable across runs.
    """

    EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or self.EPOCH

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float = 0, minutes: float = 0, hours: float = 0) -> datetime:
        self._now = self._now + timedelta(seconds=seconds, minutes=minutes, hours=hours)
        return self._now

    def set(self, moment: datetime) -> datetime:
        if moment.tzinfo is None:
            raise ValueError("ManualClock requires a timezone aware datetime")
        self._now = moment
        return self._now


def iso(moment: datetime) -> str:
    """Render an instant the one way this system renders instants."""
    return moment.astimezone(UTC).isoformat(timespec="seconds")
