"""Smoke tests for the command line surface.

The demo is the first thing anybody runs, so a crash in it is the
worst possible first impression. These check that every command exits
zero and prints the things the README says it prints.
"""

import contextlib
import io
import unittest

from handoff.cli import main


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    return code, out.getvalue()


class TestPolicyCommand(unittest.TestCase):
    def test_exits_zero(self):
        code, _ = run(["policy"])
        self.assertEqual(code, 0)

    def test_prints_every_risk_level(self):
        _, text = run(["policy"])
        for risk in ("read_only", "low", "medium", "high", "critical"):
            self.assertIn(risk, text)

    def test_prints_the_ladders(self):
        _, text = run(["policy"])
        self.assertIn("primary -> secondary", text)


class TestRosterCommand(unittest.TestCase):
    def test_lists_every_responder(self):
        code, text = run(["roster"])
        self.assertEqual(code, 0)
        for who in ("ana", "bo", "chi", "dev", "eli", "fay", "gus"):
            self.assertIn(who, text)


class TestDemoCommand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.text = run(["demo"])

    def test_exits_zero(self):
        self.assertEqual(self.code, 0)

    def test_runs_all_four_acts(self):
        for act in ("ACT 1", "ACT 2", "ACT 3", "ACT 4"):
            self.assertIn(act, self.text)

    def test_act_three_shows_the_substitution(self):
        self.assertIn("substituted for failover_database", self.text)

    def test_act_four_shows_the_raised_risk(self):
        self.assertIn("effective risk", self.text)

    def test_it_says_the_numbers_are_simulated(self):
        """The demo must not let anyone leave thinking this ran on real infra."""
        self.assertIn("deterministic simulation", self.text)
        self.assertIn("No model was called", self.text)

    def test_output_is_identical_across_runs(self):
        """The demo runs on a ManualClock, so only the random ids differ."""
        _, second = run(["demo"])
        first_lines = [x for x in self.text.splitlines() if "inc_" not in x and "esc_" not in x]
        second_lines = [x for x in second.splitlines() if "inc_" not in x and "esc_" not in x]
        self.assertEqual(first_lines, second_lines)


class TestScenariosCommand(unittest.TestCase):
    def test_exits_zero_when_every_scenario_passes(self):
        code, text = run(["scenarios", "--dir", "evals/scenarios"])
        self.assertEqual(code, 0)
        self.assertIn("0 failed", text)

    def test_prints_the_rationale_for_each_case(self):
        _, text = run(["scenarios", "--dir", "evals/scenarios"])
        self.assertIn("why:", text)


if __name__ == "__main__":
    unittest.main()
