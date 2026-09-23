import unittest

from handoff.core.types import Autonomy, OnExpiry, Risk, Severity


class TestRiskOrdering(unittest.TestCase):
    def test_ranks_ascend(self):
        ordered = [Risk.READ_ONLY, Risk.LOW, Risk.MEDIUM, Risk.HIGH, Risk.CRITICAL]
        self.assertEqual([r.rank for r in ordered], [0, 1, 2, 3, 4])

    def test_comparison(self):
        self.assertTrue(Risk.LOW < Risk.HIGH)
        self.assertTrue(Risk.HIGH <= Risk.HIGH)
        self.assertFalse(Risk.CRITICAL < Risk.LOW)

    def test_sortable(self):
        pool = [Risk.HIGH, Risk.READ_ONLY, Risk.MEDIUM]
        self.assertEqual(sorted(pool, key=lambda r: r.rank)[0], Risk.READ_ONLY)


class TestAutonomy(unittest.TestCase):
    def test_only_guarded_and_autonomous_execute(self):
        self.assertFalse(Autonomy.OBSERVE.may_execute)
        self.assertFalse(Autonomy.SUGGEST.may_execute)
        self.assertTrue(Autonomy.GUARDED.may_execute)
        self.assertTrue(Autonomy.AUTONOMOUS.may_execute)


class TestOnExpiry(unittest.TestCase):
    def test_there_is_no_allow_on_expiry(self):
        """Auto approving a timed out escalation is not offered as an option.

        This test exists so that anyone who adds ALLOW has to delete a test
        that says why it is absent, rather than quietly widening the enum.
        """
        self.assertNotIn("allow", [m.value for m in OnExpiry])


class TestSeverity(unittest.TestCase):
    def test_sev1_is_most_severe(self):
        self.assertEqual(min(Severity, key=lambda s: s.rank), Severity.SEV1)


if __name__ == "__main__":
    unittest.main()
