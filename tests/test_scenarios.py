"""The scenario suite, run as part of the unit tests.

Keeping these in the normal suite means a behavioural regression fails
the same command as a broken function, rather than waiting for somebody
to remember to run make scenarios.
"""

import unittest
from pathlib import Path

from handoff.evalsvc import run_directory
from handoff.evalsvc.scenario import parse

SCENARIO_DIR = Path("evals/scenarios")


class TestScenarioSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_directory(SCENARIO_DIR)

    def test_the_suite_is_not_empty(self):
        self.assertGreaterEqual(len(self.report.results), 10)

    def test_every_scenario_passes(self):
        failed = [
            f"{r.name}: {'; '.join(r.failures)}"
            for r in self.report.results if not r.passed
        ]
        self.assertEqual(failed, [], "\n".join(failed))

    def test_the_report_serialises(self):
        data = self.report.to_dict()
        self.assertEqual(data["failed"], 0)
        self.assertEqual(len(data["results"]), len(self.report.results))


class TestScenarioHygiene(unittest.TestCase):
    def setUp(self):
        self.scenarios = [parse(p) for p in sorted(SCENARIO_DIR.glob("*.yaml"))]

    def test_every_scenario_explains_itself(self):
        for scenario in self.scenarios:
            self.assertGreater(
                len(scenario.why_this_case_exists.split()), 8,
                f"{scenario.name} has a rationale too short to be one",
            )

    def test_every_scenario_asserts_something(self):
        for scenario in self.scenarios:
            expect = scenario.expect
            asserted = any([
                expect.end_state, expect.executed, expect.not_executed,
                expect.escalated, expect.substituted, expect.confirmed,
                expect.contested, expect.rejected,
            ])
            self.assertTrue(asserted, f"{scenario.name} asserts nothing")

    def test_names_are_unique(self):
        names = [s.name for s in self.scenarios]
        self.assertEqual(len(names), len(set(names)))

    def test_the_suite_covers_both_ends_of_the_autonomy_range(self):
        levels = {str(s.autonomy) for s in self.scenarios}
        self.assertIn("observe", levels)
        self.assertIn("autonomous", levels)
        self.assertIn("guarded", levels)

    def test_at_least_one_scenario_asserts_an_action_did_not_run(self):
        """Negative assertions are the load bearing ones here.

        A suite that only checks what did happen cannot tell the
        difference between a system that declined an action and one that
        never got round to it.
        """
        self.assertTrue(any(s.expect.not_executed for s in self.scenarios))


if __name__ == "__main__":
    unittest.main()
