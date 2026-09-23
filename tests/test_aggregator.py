import unittest

from handoff.agents.base import Finding, WorkerResult
from handoff.supervisor.aggregator import aggregate


def result(worker, *findings, ok=True, error=""):
    return WorkerResult(f"sub_{worker}", worker, findings=list(findings), ok=ok, error=error)


def finding(source, supports=(), contradicts=(), confidence=0.9):
    return Finding(source=source, claim="x", confidence=confidence,
                   supports=supports, contradicts=contradicts)


class TestFindingValidation(unittest.TestCase):
    def test_confidence_must_be_a_probability(self):
        with self.assertRaises(ValueError):
            Finding("w", "c", 1.5)
        with self.assertRaises(ValueError):
            Finding("w", "c", -0.1)

    def test_cannot_support_and_contradict_the_same_hypothesis(self):
        with self.assertRaises(ValueError):
            Finding("w", "c", 0.5, supports=("h",), contradicts=("h",))


class TestAggregation(unittest.TestCase):
    def test_support_accumulates_across_workers(self):
        agg = aggregate([
            result("a", finding("a", supports=("h",), confidence=0.5)),
            result("b", finding("b", supports=("h",), confidence=0.4)),
        ])
        self.assertAlmostEqual(agg.hypotheses["h"].support, 0.9)
        self.assertEqual(agg.hypotheses["h"].supporters, ("a", "b"))

    def test_uncontested_and_strong_is_confirmed(self):
        agg = aggregate([result("a", finding("a", supports=("h",), confidence=0.8))])
        self.assertEqual(agg.confirmed(0.6), ["h"])

    def test_below_threshold_is_not_confirmed(self):
        agg = aggregate([result("a", finding("a", supports=("h",), confidence=0.3))])
        self.assertEqual(agg.confirmed(0.6), [])

    def test_pure_contradiction_is_rejected(self):
        agg = aggregate([result("a", finding("a", contradicts=("h",), confidence=0.9))])
        self.assertEqual(agg.rejected(0.6), ["h"])
        self.assertEqual(agg.confirmed(0.6), [])


class TestContest(unittest.TestCase):
    def test_two_confident_opposites_are_contested(self):
        agg = aggregate([
            result("a", finding("a", supports=("h",), confidence=0.9)),
            result("b", finding("b", contradicts=("h",), confidence=0.8)),
        ])
        self.assertTrue(agg.hypotheses["h"].contested)
        self.assertEqual([v.name for v in agg.contested()], ["h"])

    def test_a_contested_hypothesis_is_never_confirmed(self):
        agg = aggregate([
            result("a", finding("a", supports=("h",), confidence=0.95)),
            result("b", finding("b", contradicts=("h",), confidence=0.1)),
        ])
        self.assertEqual(agg.confirmed(0.6), [])

    def test_contest_is_about_voices_not_net_score(self):
        """Two hesitant workers net near zero but are not in conflict."""
        quiet = aggregate([result("a", finding("a", supports=("h",), confidence=0.05))])
        self.assertFalse(quiet.hypotheses["h"].contested)

        loud = aggregate([
            result("a", finding("a", supports=("h",), confidence=0.9)),
            result("b", finding("b", contradicts=("h",), confidence=0.85)),
        ])
        self.assertTrue(loud.hypotheses["h"].contested)
        self.assertAlmostEqual(loud.hypotheses["h"].net, 0.05, places=4)


class TestDegraded(unittest.TestCase):
    def test_a_failed_worker_marks_the_aggregate_degraded(self):
        agg = aggregate([
            result("a", finding("a", supports=("h",))),
            result("b", ok=False, error="timeout"),
        ])
        self.assertTrue(agg.degraded)
        self.assertEqual(len(agg.failures), 1)
        self.assertIn("timeout", agg.summary())

    def test_a_failed_workers_findings_are_not_counted(self):
        agg = aggregate([result("b", finding("b", supports=("h",)), ok=False, error="x")])
        self.assertEqual(agg.hypotheses, {})


if __name__ == "__main__":
    unittest.main()
