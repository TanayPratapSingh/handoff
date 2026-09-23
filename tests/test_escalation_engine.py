import unittest

from handoff.bus.events import EventKind
from handoff.bus.journal import Journal
from handoff.core.clock import ManualClock
from handoff.core.types import Decision, OnExpiry, Risk
from handoff.escalation.engine import EscalationEngine
from handoff.escalation.policy import Policy, Rule
from handoff.escalation.request import EscalationState
from handoff.escalation.roster import Responder, Roster
from handoff.tools.builtin import build_registry
from handoff.tools.registry import Tool


def policy_with(rule: Rule, **kw) -> Policy:
    rules = {
        Risk.READ_ONLY: Rule(Risk.READ_ONLY, False, (), 0, OnExpiry.DENY),
        Risk.LOW: Rule(Risk.LOW, False, (), 0, OnExpiry.DENY),
        Risk.MEDIUM: Rule(Risk.MEDIUM, False, (), 0, OnExpiry.DENY),
        Risk.HIGH: Rule(Risk.HIGH, False, (), 0, OnExpiry.DENY),
        Risk.CRITICAL: Rule(Risk.CRITICAL, False, (), 0, OnExpiry.DENY),
    }
    rules[rule.risk] = rule
    return Policy(rules=rules, **kw)


class EngineCase(unittest.TestCase):
    """Three tiers with one responder each, so laddering is easy to follow."""

    def build(self, rule: Rule, responders=None):
        self.clock = ManualClock()
        self.journal = Journal()
        self.roster = Roster(tiers=("t1", "t2", "t3"))
        for r in responders or [
            Responder("one", "One", "t1", frozenset({"infra"})),
            Responder("two", "Two", "t2", frozenset({"infra"})),
            Responder("three", "Three", "t3", frozenset({"infra"})),
        ]:
            self.roster.add(r)
        self.registry = build_registry()
        self.engine = EscalationEngine(
            policy=policy_with(rule),
            roster=self.roster,
            journal=self.journal,
            clock=self.clock,
            registry=self.registry,
            backoff=1.0,
        )
        return self.engine

    def raise_one(self, tool_name="failover_database", args=None, reason="because"):
        tool = self.registry.get(tool_name)
        return self.engine.raise_for("inc_1", tool, args or {"target": "node-b"}, reason)

    def kinds(self):
        return [e.kind for e in self.journal]


class TestRaising(EngineCase):
    def setUp(self):
        self.build(Rule(Risk.HIGH, True, ("t1", "t2", "t3"), 300, OnExpiry.ESCALATE))

    def test_raise_assigns_to_first_tier(self):
        esc = self.raise_one()
        self.assertEqual(esc.state, EscalationState.ASSIGNED)
        self.assertEqual(esc.assignee, "one")
        self.assertEqual(esc.current_tier, "t1")

    def test_raise_emits_raised_then_assigned(self):
        self.raise_one()
        self.assertEqual(
            self.kinds(),
            [EventKind.ESCALATION_RAISED, EventKind.ESCALATION_ASSIGNED],
        )

    def test_deadline_is_now_plus_rule_seconds(self):
        esc = self.raise_one()
        self.assertEqual((esc.deadline - self.clock.now()).total_seconds(), 300)

    def test_assignment_consumes_roster_capacity(self):
        self.raise_one()
        self.assertEqual(self.roster.get("one").open_count, 1)

    def test_escalation_carries_the_tools_blast_radius(self):
        esc = self.raise_one()
        self.assertIn("reconnect", esc.blast_radius)


class TestDecisions(EngineCase):
    def setUp(self):
        self.build(Rule(Risk.HIGH, True, ("t1", "t2", "t3"), 300, OnExpiry.ESCALATE))

    def test_approve_resolves(self):
        esc = self.raise_one()
        self.engine.decide(esc.id, "one", Decision.APPROVE)
        self.assertEqual(esc.state, EscalationState.APPROVED)
        self.assertTrue(self.engine.resolution(esc).should_run)

    def test_approve_releases_capacity(self):
        esc = self.raise_one()
        self.engine.decide(esc.id, "one", Decision.APPROVE)
        self.assertEqual(self.roster.get("one").open_count, 0)

    def test_reject_is_final_and_does_not_ladder(self):
        esc = self.raise_one()
        self.engine.decide(esc.id, "one", Decision.REJECT, note="no")
        self.assertEqual(esc.state, EscalationState.REJECTED)
        self.assertEqual(len(esc.attempts), 1)
        self.assertFalse(self.engine.resolution(esc).should_run)

    def test_modify_replaces_the_arguments_that_run(self):
        esc = self.raise_one()
        self.engine.decide(esc.id, "one", Decision.MODIFY, modified_args={"target": "node-c"})
        self.assertEqual(esc.state, EscalationState.APPROVED)
        self.assertEqual(self.engine.resolution(esc).args, {"target": "node-c"})

    def test_modify_without_args_raises(self):
        esc = self.raise_one()
        with self.assertRaises(ValueError):
            self.engine.decide(esc.id, "one", Decision.MODIFY)

    def test_defer_hands_to_the_next_tier_immediately(self):
        esc = self.raise_one()
        self.engine.decide(esc.id, "one", Decision.DEFER)
        self.assertEqual(esc.assignee, "two")
        self.assertEqual(esc.state, EscalationState.ASSIGNED)

    def test_wrong_responder_cannot_decide(self):
        esc = self.raise_one()
        with self.assertRaises(ValueError) as ctx:
            self.engine.decide(esc.id, "three", Decision.APPROVE)
        self.assertIn("assigned to one", str(ctx.exception))

    def test_deciding_twice_raises(self):
        esc = self.raise_one()
        self.engine.decide(esc.id, "one", Decision.APPROVE)
        with self.assertRaises(ValueError):
            self.engine.decide(esc.id, "one", Decision.APPROVE)


class TestDeadlineEscalate(EngineCase):
    def setUp(self):
        self.build(Rule(Risk.HIGH, True, ("t1", "t2", "t3"), 300, OnExpiry.ESCALATE))

    def test_nothing_fires_before_the_deadline(self):
        self.raise_one()
        self.clock.advance(seconds=299)
        self.assertEqual(self.engine.tick(), [])

    def test_deadline_fires_exactly_on_the_boundary(self):
        esc = self.raise_one()
        self.clock.advance(seconds=300)
        self.assertEqual(self.engine.tick(), [esc])

    def test_timeout_moves_to_the_next_tier(self):
        esc = self.raise_one()
        self.clock.advance(seconds=300)
        self.engine.tick()
        self.assertEqual(esc.current_tier, "t2")
        self.assertEqual(esc.assignee, "two")
        self.assertEqual(esc.state, EscalationState.ASSIGNED)

    def test_the_unanswered_attempt_is_kept(self):
        esc = self.raise_one()
        self.clock.advance(seconds=300)
        self.engine.tick()
        self.assertEqual(len(esc.attempts), 2)
        self.assertFalse(esc.attempts[0].answered)
        self.assertIn("no answer", esc.attempts[0].describe())

    def test_timeout_releases_the_silent_responder(self):
        self.raise_one()
        self.clock.advance(seconds=300)
        self.engine.tick()
        self.assertEqual(self.roster.get("one").open_count, 0)
        self.assertEqual(self.roster.get("two").open_count, 1)

    def test_ladder_runs_out_and_exhausts(self):
        esc = self.raise_one()
        for _ in range(3):
            self.clock.advance(seconds=300)
            self.engine.tick()
        self.assertEqual(esc.state, EscalationState.EXHAUSTED)
        self.assertEqual(esc.tiers_tried(), ["t1", "t2", "t3"])
        self.assertFalse(self.engine.resolution(esc).should_run)

    def test_exhaustion_releases_every_responder(self):
        self.raise_one()
        for _ in range(3):
            self.clock.advance(seconds=300)
            self.engine.tick()
        self.assertEqual([r.open_count for r in self.roster.responders.values()], [0, 0, 0])

    def test_a_late_approval_after_exhaustion_is_refused(self):
        esc = self.raise_one()
        for _ in range(3):
            self.clock.advance(seconds=300)
            self.engine.tick()
        with self.assertRaises(ValueError):
            self.engine.decide(esc.id, "three", Decision.APPROVE)


if __name__ == "__main__":
    unittest.main()
