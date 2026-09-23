import unittest
from datetime import UTC, datetime

from handoff.core.clock import ManualClock, SystemClock, iso


class TestManualClock(unittest.TestCase):
    def test_starts_at_fixed_epoch(self):
        self.assertEqual(ManualClock().now(), ManualClock.EPOCH)

    def test_advance_is_cumulative(self):
        c = ManualClock()
        c.advance(minutes=5)
        c.advance(minutes=5)
        self.assertEqual((c.now() - ManualClock.EPOCH).total_seconds(), 600)

    def test_advance_mixed_units(self):
        c = ManualClock()
        c.advance(hours=1, minutes=30, seconds=15)
        self.assertEqual((c.now() - ManualClock.EPOCH).total_seconds(), 5415)

    def test_set_requires_tzaware(self):
        with self.assertRaises(ValueError):
            ManualClock().set(datetime(2026, 5, 1))

    def test_set_moves_clock(self):
        c = ManualClock()
        target = datetime(2026, 6, 1, tzinfo=UTC)
        c.set(target)
        self.assertEqual(c.now(), target)


class TestSystemClock(unittest.TestCase):
    def test_is_tzaware_utc(self):
        now = SystemClock().now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.utcoffset().total_seconds(), 0)


class TestIso(unittest.TestCase):
    def test_second_precision_no_microseconds(self):
        self.assertEqual(iso(ManualClock.EPOCH), "2026-01-01T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
