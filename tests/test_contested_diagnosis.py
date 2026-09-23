"""A world built so that two analysts reach opposite conclusions.

The log analyst sees a high error rate and calls the service degraded.
The metrics analyst sees healthy p99 latency and says it is not. Neither
is lying and neither is low confidence. This is the case where averaging
or taking the highest confidence would produce a clean answer from a
system that does not actually have one.
"""

import unittest

from handoff.bus.events import EventKind
from handoff.core.clock import ManualClock
from handoff.core.types import Decision, Risk
from handoff.supervisor.incident import Incident, RunState
from handoff.system import build
from handoff.tools.world import Service, World


def disagreeing_world() -> World:
    return World(
        services={
            # 0.25 error rate gives 750 error lines in the 15 minute window, so
            # the log analyst supports service_degraded. 300ms p99 is under the
            # 1000ms saturation bar, so the metrics analyst contradicts it.
            "checkout": Service(
                "checkout", replicas=6, error_rate=0.25, latency_p99_ms=300, healthy=True
            ),
        }
    )


class ContestedCase(unittest.TestCase):
    def setUp(self):
        self.clock = ManualClock()
        self.world = disagreeing_world()
        self.sys = build(clock=self.clock, world=self.world, seed=7)
        self.run = self.sys.supervisor.open(
            Incident(
                title="Checkout error rate is up but latency looks fine",
                service="checkout",
                symptom="errors without latency",
            )
        )
        self.sys.supervisor.advance(self.run)


class TestContestIsDetected(ContestedCase):
    def test_the_two_analysts_disagree(self):
        view = self.run.aggregate.hypotheses["service_degraded"]
        self.assertTrue(view.contested)
        self.assertEqual(view.supporters, ("log_analyst",))
        self.assertEqual(view.detractors, ("metrics_analyst",))

    def test_conflict_is_journalled(self):
        conflicts = self.sys.journal.of_kind(EventKind.CONFLICT_DETECTED)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].detail["hypothesis"], "service_degraded")

    def test_a_contested_hypothesis_is_not_confirmed(self):
        self.assertNotIn("service_degraded", self.run.aggregate.confirmed())

    def test_the_contest_is_recorded_in_the_run_notes(self):
        self.assertTrue(any("contested diagnosis" in n for n in self.run.notes))


class TestContestRaisesRisk(ContestedCase):
    def test_restart_is_low_risk_on_its_own(self):
        self.assertEqual(self.sys.supervisor.tools.get("restart_service").risk, Risk.LOW)

    def test_but_a_contested_diagnosis_pushes_it_to_medium(self):
        proposal = next(p for p in self.run.aggregate.proposals if p.tool == "restart_service")
        self.assertEqual(self.sys.supervisor.effective_risk(proposal, self.run), Risk.MEDIUM)

    def test_so_a_low_risk_action_now_asks_a_human(self):
        """The whole point. Uncertainty about the diagnosis buys a review."""
        self.assertEqual(self.run.state, RunState.AWAITING_HUMAN)
        escalation = self.sys.engine.get(self.run.blocked_on)
        self.assertEqual(escalation.tool, "restart_service")

    def test_the_human_is_told_why_the_risk_was_raised(self):
        escalation = self.sys.engine.get(self.run.blocked_on)
        self.assertIn("contested", escalation.reason)

    def test_the_journal_records_both_risk_levels(self):
        proposed = self.sys.journal.of_kind(EventKind.ACTION_PROPOSED)
        restart = next(e for e in proposed if e.detail["tool"] == "restart_service")
        self.assertEqual(restart.detail["declared_risk"], "low")
        self.assertEqual(restart.detail["effective_risk"], "medium")

    def test_an_uncontested_run_does_not_raise_the_risk(self):
        clean = build(clock=ManualClock(), world=World.sample(), seed=7)
        run = clean.supervisor.open(
            Incident(
                title="Checkout latency",
                service="checkout",
                symptom="latency",
            )
        )
        clean.supervisor.advance(run)
        restarts = [a for a in run.executed if a.tool == "restart_service"]
        self.assertEqual(len(restarts), 1)
        self.assertEqual(restarts[0].approved_by, "")


class TestResolvingAContest(ContestedCase):
    def test_a_human_can_approve_through_the_contest(self):
        escalation = self.sys.engine.get(self.run.blocked_on)
        self.sys.engine.decide(
            escalation.id,
            escalation.assignee,
            Decision.APPROVE,
            note="logs are right, metrics window is too coarse",
        )
        self.sys.supervisor.advance(self.run)
        self.assertIn("restart_service", [a.tool for a in self.run.executed])

    def test_the_approver_is_recorded_against_the_action(self):
        escalation = self.sys.engine.get(self.run.blocked_on)
        who = escalation.assignee
        self.sys.engine.decide(escalation.id, who, Decision.APPROVE)
        self.sys.supervisor.advance(self.run)
        restart = next(a for a in self.run.executed if a.tool == "restart_service")
        self.assertEqual(restart.approved_by, who)

    def test_silence_on_a_contested_low_risk_action_ladders_not_runs(self):
        escalation = self.sys.engine.get(self.run.blocked_on)
        self.assertEqual(escalation.on_expiry.value, "escalate")
        self.clock.advance(seconds=300)
        self.sys.engine.tick()
        self.assertEqual(escalation.current_tier, "secondary")


if __name__ == "__main__":
    unittest.main()
