import unittest

from handoff.bus.events import EventKind
from handoff.core.clock import ManualClock
from handoff.core.types import Autonomy, Decision, Severity
from handoff.supervisor.incident import Incident, RunState
from handoff.system import build
from handoff.tools.world import World


class SupervisorCase(unittest.TestCase):
    def build_system(self, autonomy=None, world=None):
        self.clock = ManualClock()
        self.world = world if world is not None else World.sample()
        self.sys = build(clock=self.clock, world=self.world, autonomy=autonomy, seed=7)
        return self.sys

    def open_checkout(self):
        return self.sys.supervisor.open(
            Incident(
                title="Checkout p99 latency spike",
                service="checkout",
                symptom="latency and errors after deploy",
                severity=Severity.SEV2,
            )
        )

    def kinds(self):
        return [e.kind for e in self.sys.journal]


class TestFanOut(SupervisorCase):
    def setUp(self):
        self.build_system()
        self.run = self.open_checkout()
        self.sys.supervisor.advance(self.run)

    def test_every_diagnostic_capability_was_dispatched(self):
        routed = [
            e.detail["capability"] for e in self.sys.journal.of_kind(EventKind.SUBTASK_ROUTED)
        ]
        self.assertEqual(
            sorted(routed), ["logs", "metrics", "remediation", "replication", "runbook"]
        )

    def test_remediation_runs_after_the_analysts(self):
        order = [e.detail["capability"] for e in self.sys.journal.of_kind(EventKind.SUBTASK_ROUTED)]
        self.assertEqual(order[-1], "remediation")

    def test_evidence_against_a_hypothesis_rejects_it(self):
        """Replication lag is 0.4s against a 5s threshold, so no failover."""
        self.assertIn("database_fault", self.run.aggregate.rejected())
        self.assertNotIn("failover_database", [p.tool for p in self.run.queue])

    def test_workers_cannot_see_mutating_tools(self):
        readonly = self.sys.supervisor._readonly_tools()
        self.assertEqual(
            sorted(readonly.names()),
            ["read_logs", "read_metrics", "read_replication", "search_runbooks"],
        )


class TestGuardedAutonomy(SupervisorCase):
    def setUp(self):
        self.build_system()
        self.run = self.open_checkout()
        self.sys.supervisor.advance(self.run)

    def test_low_risk_actions_run_without_asking(self):
        self.assertEqual(
            [a.tool for a in self.run.executed],
            ["page_vendor", "restart_service"],
        )

    def test_medium_risk_action_stops_and_waits(self):
        self.assertEqual(self.run.state, RunState.AWAITING_HUMAN)
        escalation = self.sys.engine.get(self.run.blocked_on)
        self.assertEqual(escalation.tool, "scale_deployment")

    def test_the_escalation_names_a_real_person(self):
        escalation = self.sys.engine.get(self.run.blocked_on)
        self.assertIn(escalation.assignee, self.sys.roster.responders)

    def test_advancing_again_while_blocked_changes_nothing(self):
        before = len(self.sys.journal)
        self.sys.supervisor.advance(self.run)
        self.assertEqual(len(self.sys.journal), before)
        self.assertEqual(self.run.state, RunState.AWAITING_HUMAN)

    def test_approval_resumes_and_executes(self):
        escalation = self.sys.engine.get(self.run.blocked_on)
        self.sys.engine.decide(escalation.id, escalation.assignee, Decision.APPROVE)
        self.sys.supervisor.advance(self.run)
        self.assertIn("scale_deployment", [a.tool for a in self.run.executed])
        self.assertTrue(self.run.state.is_terminal)

    def test_rejection_resumes_without_executing(self):
        escalation = self.sys.engine.get(self.run.blocked_on)
        self.sys.engine.decide(
            escalation.id, escalation.assignee, Decision.REJECT, note="peak traffic"
        )
        self.sys.supervisor.advance(self.run)
        self.assertNotIn("scale_deployment", [a.tool for a in self.run.executed])
        self.assertTrue(any("not taken" in n for n in self.run.notes))

    def test_a_modified_approval_runs_the_edited_arguments(self):
        escalation = self.sys.engine.get(self.run.blocked_on)
        self.sys.engine.decide(
            escalation.id,
            escalation.assignee,
            Decision.MODIFY,
            modified_args={"service": "checkout", "replicas": 9},
        )
        self.sys.supervisor.advance(self.run)
        scaled = [a for a in self.run.executed if a.tool == "scale_deployment"]
        self.assertEqual(scaled[0].args["replicas"], 9)


class TestNobodyAnswers(SupervisorCase):
    def test_the_medium_rule_ladders_then_resolves(self):
        self.build_system()
        self.run = self.open_checkout()
        self.sys.supervisor.advance(self.run)
        first = self.sys.engine.get(self.run.blocked_on)
        first_assignee = first.assignee

        self.clock.advance(seconds=300)
        self.sys.engine.tick()
        self.assertNotEqual(first.assignee, first_assignee)
        self.assertEqual(first.current_tier, "secondary")

        self.sys.engine.decide(first.id, first.assignee, Decision.APPROVE)
        self.sys.supervisor.advance(self.run)
        self.assertIn("scale_deployment", [a.tool for a in self.run.executed])

    def test_silence_all_the_way_down_leaves_the_action_untaken(self):
        self.build_system()
        self.run = self.open_checkout()
        self.sys.supervisor.advance(self.run)
        for _ in range(4):
            self.clock.advance(seconds=600)
            self.sys.engine.tick()
        self.sys.supervisor.advance(self.run)
        self.assertNotIn("scale_deployment", [a.tool for a in self.run.executed])
        self.assertTrue(self.run.state.is_terminal)


class TestAutonomyLevels(SupervisorCase):
    def test_observe_executes_nothing_at_all(self):
        self.build_system(autonomy=Autonomy.OBSERVE)
        self.run = self.open_checkout()
        self.sys.supervisor.advance(self.run)
        self.assertEqual(self.run.executed, [])
        self.assertTrue(any(e.kind is EventKind.POLICY_BLOCKED for e in self.sys.journal))

    def test_observe_still_produces_a_diagnosis(self):
        self.build_system(autonomy=Autonomy.OBSERVE)
        self.run = self.open_checkout()
        self.sys.supervisor.advance(self.run)
        self.assertIn("service_degraded", self.run.aggregate.confirmed())

    def test_autonomous_never_pauses(self):
        self.build_system(autonomy=Autonomy.AUTONOMOUS)
        self.run = self.open_checkout()
        self.sys.supervisor.advance(self.run)
        self.assertNotEqual(self.run.state, RunState.AWAITING_HUMAN)
        self.assertEqual(self.sys.engine.all(), [])

    def test_autonomous_reaches_further_into_the_queue(self):
        self.build_system(autonomy=Autonomy.AUTONOMOUS)
        self.run = self.open_checkout()
        self.sys.supervisor.advance(self.run)
        self.assertIn("scale_deployment", [a.tool for a in self.run.executed])


class TestVerification(SupervisorCase):
    def test_a_healthy_service_needs_no_action(self):
        world = World.sample()
        self.build_system(world=world)
        run = self.sys.supervisor.open(
            Incident(
                title="Search feels slow",
                service="payments",
                symptom="latency",
            )
        )
        self.sys.supervisor.advance(run)
        self.assertEqual(run.executed, [])
        self.assertEqual(run.state, RunState.RESOLVED)

    def test_resolution_is_verified_against_metrics_not_assumed(self):
        self.build_system()
        run = self.open_checkout()
        self.sys.supervisor.advance(run)
        escalation = self.sys.engine.get(run.blocked_on)
        self.sys.engine.decide(escalation.id, escalation.assignee, Decision.APPROVE)
        self.sys.supervisor.advance(run)
        self.assertEqual(run.state, RunState.RESOLVED)
        self.assertTrue(any("verified" in n for n in run.notes))
        self.assertFalse(
            self.sys.supervisor.tools.get("read_metrics").run(self.world, {"service": "checkout"})[
                "saturated"
            ]
        )


if __name__ == "__main__":
    unittest.main()
