import itertools
import tempfile
import unittest
from pathlib import Path

from handoff.core.errors import ConfigError
from handoff.core.types import Autonomy, OnExpiry, Risk
from handoff.escalation.policy import Policy, Rule

_TMP = Path(tempfile.mkdtemp(prefix="handoff-policy-"))
_COUNTER = itertools.count()


def write(text):
    """Write a policy file and return its path.

    Policy.from_config takes a path, so the file has to outlive the
    writing of it. mkdtemp plus write_text does that without leaving a
    dangling handle open for the rest of the test run.
    """
    path = _TMP / f"policy-{next(_COUNTER)}.yaml"
    path.write_text(text, encoding="utf-8")
    return path


FULL = """
autonomy: guarded
escalate_at_or_above: medium
rules:
  read_only:
    requires_approval: false
  low:
    requires_approval: false
  medium:
    requires_approval: true
    ladder: [primary]
    deadline_seconds: 300
    on_expiry: escalate
  high:
    requires_approval: true
    ladder: [primary, secondary]
    deadline_seconds: 180
    on_expiry: safe_fallback
  critical:
    requires_approval: true
    ladder: [a, b]
    deadline_seconds: 600
    on_expiry: hold
    quorum: 2
"""


class TestRuleValidation(unittest.TestCase):
    def test_approval_without_ladder_rejected(self):
        with self.assertRaises(ConfigError):
            Rule(Risk.HIGH, True, (), 60, OnExpiry.DENY)

    def test_nonpositive_deadline_rejected(self):
        with self.assertRaises(ConfigError):
            Rule(Risk.HIGH, True, ("a",), 0, OnExpiry.DENY)

    def test_quorum_larger_than_ladder_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            Rule(Risk.HIGH, True, ("a",), 60, OnExpiry.DENY, quorum=2)
        self.assertIn("never be satisfied", str(ctx.exception))


class TestPolicyLoading(unittest.TestCase):
    def test_loads_every_risk_level(self):
        policy = Policy.from_config(write(FULL))
        self.assertEqual(len(policy.rules), 5)
        self.assertEqual(policy.rule_for(Risk.CRITICAL).quorum, 2)

    def test_missing_on_expiry_rejected_with_an_explanation(self):
        bad = FULL.replace("    on_expiry: escalate\n", "")
        with self.assertRaises(ConfigError) as ctx:
            Policy.from_config(write(bad))
        self.assertIn("on_expiry", str(ctx.exception))

    def test_missing_risk_level_rejected(self):
        bad = FULL.replace("  low:\n    requires_approval: false\n", "")
        with self.assertRaises(ConfigError) as ctx:
            Policy.from_config(write(bad))
        self.assertIn("low", str(ctx.exception))

    def test_unknown_on_expiry_rejected(self):
        bad = FULL.replace("on_expiry: escalate", "on_expiry: allow")
        with self.assertRaises(ConfigError) as ctx:
            Policy.from_config(write(bad))
        self.assertIn("allow", str(ctx.exception))

    def test_shipped_config_loads(self):
        policy = Policy.from_config("config/policy.yaml")
        self.assertEqual(policy.autonomy, Autonomy.GUARDED)
        self.assertEqual(policy.rule_for(Risk.CRITICAL).on_expiry, OnExpiry.HOLD)


class TestNeedsHuman(unittest.TestCase):
    def setUp(self):
        self.policy = Policy.from_config(write(FULL))

    def test_guarded_skips_below_threshold(self):
        self.assertFalse(self.policy.needs_human(Risk.READ_ONLY))
        self.assertFalse(self.policy.needs_human(Risk.LOW))
        self.assertTrue(self.policy.needs_human(Risk.MEDIUM))
        self.assertTrue(self.policy.needs_human(Risk.CRITICAL))

    def test_autonomous_never_asks(self):
        p = self.policy.with_autonomy(Autonomy.AUTONOMOUS)
        self.assertFalse(p.needs_human(Risk.CRITICAL))

    def test_observe_forbids_everything_that_mutates(self):
        p = self.policy.with_autonomy(Autonomy.OBSERVE)
        self.assertFalse(p.forbids(Risk.READ_ONLY))
        self.assertTrue(p.forbids(Risk.LOW))
        self.assertTrue(p.forbids(Risk.CRITICAL))

    def test_guarded_forbids_nothing_outright(self):
        self.assertFalse(self.policy.forbids(Risk.CRITICAL))

    def test_raising_the_threshold_widens_autonomy(self):
        from dataclasses import replace

        p = replace(self.policy, escalate_at_or_above=Risk.HIGH)
        self.assertFalse(p.needs_human(Risk.MEDIUM))
        self.assertTrue(p.needs_human(Risk.HIGH))


if __name__ == "__main__":
    unittest.main()
