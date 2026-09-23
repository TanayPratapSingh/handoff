import json
import tempfile
import unittest
from pathlib import Path

from handoff.bus.events import Event, EventKind
from handoff.bus.journal import Journal
from handoff.core.clock import ManualClock


class JournalCase(unittest.TestCase):
    def setUp(self):
        self.clock = ManualClock()
        self.journal = Journal()

    def emit(self, kind, incident="inc_1", **detail):
        return self.journal.append(
            Event(kind=kind, incident_id=incident, at=self.clock.now(), detail=detail)
        )


class TestAppend(JournalCase):
    def test_length_and_order_preserved(self):
        self.emit(EventKind.INCIDENT_OPENED)
        self.clock.advance(seconds=1)
        self.emit(EventKind.PLAN_BUILT)
        self.assertEqual(len(self.journal), 2)
        self.assertEqual(self.journal.all()[0].kind, EventKind.INCIDENT_OPENED)

    def test_events_have_unique_ids(self):
        ids = {self.emit(EventKind.PLAN_BUILT).id for _ in range(50)}
        self.assertEqual(len(ids), 50)


class TestQueries(JournalCase):
    def setUp(self):
        super().setUp()
        self.emit(EventKind.INCIDENT_OPENED, incident="inc_a")
        self.emit(EventKind.INCIDENT_OPENED, incident="inc_b")
        self.emit(EventKind.ESCALATION_RAISED, incident="inc_a")

    def test_filter_by_incident(self):
        self.assertEqual(len(self.journal.for_incident("inc_a")), 2)
        self.assertEqual(len(self.journal.for_incident("inc_b")), 1)

    def test_filter_by_kind(self):
        self.assertEqual(len(self.journal.of_kind(EventKind.INCIDENT_OPENED)), 2)

    def test_count_and_last(self):
        self.assertEqual(self.journal.count(EventKind.ESCALATION_RAISED), 1)
        self.assertEqual(self.journal.last().kind, EventKind.ESCALATION_RAISED)
        self.assertEqual(self.journal.last(EventKind.INCIDENT_OPENED).incident_id, "inc_b")

    def test_last_of_absent_kind_is_none(self):
        self.assertIsNone(self.journal.last(EventKind.INCIDENT_CLOSED))


class TestSubscribers(JournalCase):
    def test_subscriber_sees_events_in_order(self):
        seen = []
        self.journal.subscribe(seen.append)
        self.emit(EventKind.INCIDENT_OPENED)
        self.emit(EventKind.PLAN_BUILT)
        self.assertEqual([e.kind for e in seen], [EventKind.INCIDENT_OPENED, EventKind.PLAN_BUILT])

    def test_raising_subscriber_propagates(self):
        def boom(_):
            raise RuntimeError("pager down")

        self.journal.subscribe(boom)
        with self.assertRaises(RuntimeError):
            self.emit(EventKind.INCIDENT_OPENED)

    def test_event_is_recorded_even_when_subscriber_raises(self):
        self.journal.subscribe(lambda _: (_ for _ in ()).throw(RuntimeError()))
        with self.assertRaises(RuntimeError):
            self.emit(EventKind.INCIDENT_OPENED)
        self.assertEqual(len(self.journal), 1)


class TestSink(unittest.TestCase):
    def test_writes_one_json_object_per_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            sink = Path(tmp) / "nested" / "run.journal"
            journal = Journal(sink=sink)
            clock = ManualClock()
            for kind in (EventKind.INCIDENT_OPENED, EventKind.PLAN_BUILT):
                journal.append(Event(kind=kind, incident_id="inc_1", at=clock.now()))
            lines = sink.read_text().strip().splitlines()
            self.assertEqual(len(lines), 2)
            first = json.loads(lines[0])
            self.assertEqual(first["kind"], "incident.opened")
            self.assertEqual(first["at"], "2026-01-01T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
