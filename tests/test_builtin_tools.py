import unittest

from handoff.core.types import Risk
from handoff.tools.builtin import build_registry
from handoff.tools.world import World


class BuiltinCase(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()
        self.world = World.sample()

    def call(self, name, **args):
        tool = self.registry.get(name)
        return tool.run(self.world, tool.validate(args))


class TestRegistryShape(BuiltinCase):
    def test_every_tool_has_a_runner(self):
        missing = [t.name for t in self.registry.tools.values() if t.run is None]
        self.assertEqual(missing, [])

    def test_every_tool_declares_blast_radius(self):
        missing = [t.name for t in self.registry.tools.values() if not t.blast_radius]
        self.assertEqual(missing, [])

    def test_irreversible_tools_are_high_or_critical(self):
        for t in self.registry.tools.values():
            if not t.reversible:
                self.assertGreaterEqual(t.risk.rank, Risk.HIGH.rank, t.name)

    def test_every_irreversible_tool_declares_a_fallback(self):
        for t in self.registry.tools.values():
            if not t.reversible:
                self.assertIsNotNone(t.safe_fallback, t.name)

    def test_fallbacks_are_consistent(self):
        self.assertEqual(self.registry.check_fallbacks(), [])


class TestReadOnlyToolsChangeNothing(BuiltinCase):
    def test_snapshot_identical_after_every_readonly_call(self):
        before = self.world.snapshot()
        self.call("read_logs", service="checkout")
        self.call("read_metrics", service="checkout")
        self.call("read_replication")
        self.call("search_runbooks", symptom="latency is high")
        self.assertEqual(self.world.snapshot(), before)


class TestMutatingTools(BuiltinCase):
    def test_restart_marks_service_healthy(self):
        out = self.call("restart_service", service="checkout")
        self.assertTrue(out["healthy"])
        self.assertEqual(self.world.service("checkout").restarts, 1)

    def test_scale_reports_before_and_after(self):
        out = self.call("scale_deployment", service="search", replicas=8)
        self.assertEqual((out["replicas_before"], out["replicas_after"]), (2, 8))

    def test_rollback_swaps_versions(self):
        out = self.call("rollback_release", service="checkout")
        self.assertEqual(out["from"], "v1.4.2")
        self.assertEqual(out["to"], "v1.4.1")

    def test_enable_read_only_protects_data(self):
        self.call("enable_read_only")
        self.assertTrue(self.world.database.read_only)

    def test_drain_node_is_idempotent(self):
        self.call("drain_node", node="node-x")
        self.call("drain_node", node="node-x")
        self.assertEqual(self.world.drained_nodes, ["node-x"])


class TestDestructiveTools(BuiltinCase):
    def test_failover_promotes_replica_and_demotes_primary(self):
        out = self.call("failover_database", target="node-b")
        self.assertEqual(out["from"], "node-a")
        self.assertEqual(self.world.database.primary, "node-b")
        self.assertIn("node-a", self.world.database.replicas)

    def test_failover_to_a_non_replica_raises(self):
        with self.assertRaises(ValueError):
            self.call("failover_database", target="node-z")

    def test_delete_volume_reports_unrecoverable_without_snapshot(self):
        out = self.call("delete_volume", volume="pvc-7")
        self.assertFalse(out["recoverable"])

    def test_snapshot_then_delete_is_recoverable(self):
        self.call("snapshot_volume", volume="pvc-7")
        out = self.call("delete_volume", volume="pvc-7")
        self.assertTrue(out["recoverable"])


if __name__ == "__main__":
    unittest.main()
