import tempfile
import unittest
from pathlib import Path

from handoff.core.errors import ConfigError
from handoff.escalation.roster import Responder, Roster


class TestResponder(unittest.TestCase):
    def test_capacity_respects_max_concurrent(self):
        r = Responder("a", "A", "primary", max_concurrent=2)
        self.assertTrue(r.has_capacity)
        r.open_count = 2
        self.assertFalse(r.has_capacity)

    def test_unavailable_has_no_capacity(self):
        r = Responder("a", "A", "primary", available=False)
        self.assertFalse(r.has_capacity)

    def test_skill_gate(self):
        r = Responder("a", "A", "primary", skills=frozenset({"database"}))
        self.assertTrue(r.can_approve(None))
        self.assertTrue(r.can_approve("database"))
        self.assertFalse(r.can_approve("network"))


class TestRoster(unittest.TestCase):
    def setUp(self):
        self.roster = Roster(tiers=("primary", "secondary"))
        self.roster.add(Responder("ana", "Ana", "primary", frozenset({"db"}), max_concurrent=2))
        self.roster.add(Responder("bo", "Bo", "primary", frozenset({"app"}), max_concurrent=2))
        self.roster.add(Responder("chi", "Chi", "secondary", frozenset({"db"})))

    def test_duplicate_id_rejected(self):
        with self.assertRaises(ConfigError):
            self.roster.add(Responder("ana", "Other", "primary"))

    def test_unknown_tier_rejected(self):
        with self.assertRaises(ConfigError):
            self.roster.add(Responder("zed", "Zed", "nonexistent"))

    def test_candidates_filtered_by_skill(self):
        self.assertEqual([r.id for r in self.roster.candidates("primary", "db")], ["ana"])
        self.assertEqual([r.id for r in self.roster.candidates("primary", "app")], ["bo"])

    def test_candidates_sorted_by_load_then_id(self):
        self.assertEqual([r.id for r in self.roster.candidates("primary")], ["ana", "bo"])
        self.roster.acquire("ana")
        self.assertEqual([r.id for r in self.roster.candidates("primary")], ["bo", "ana"])

    def test_saturated_responder_drops_out(self):
        self.roster.acquire("ana")
        self.roster.acquire("ana")
        self.assertEqual([r.id for r in self.roster.candidates("primary")], ["bo"])

    def test_release_restores_capacity(self):
        self.roster.acquire("ana")
        self.roster.release("ana")
        self.assertEqual(self.roster.get("ana").open_count, 0)

    def test_release_never_goes_negative(self):
        self.roster.release("ana")
        self.assertEqual(self.roster.get("ana").open_count, 0)

    def test_unavailable_responder_excluded(self):
        self.roster.set_available("ana", False)
        self.assertEqual([r.id for r in self.roster.candidates("primary")], ["bo"])


class TestRosterConfig(unittest.TestCase):
    def test_shipped_roster_loads(self):
        roster = Roster.from_config("config/roster.yaml")
        self.assertEqual(len(roster.responders), 7)
        self.assertEqual(len(roster.tiers), 5)

    def test_shipped_roster_covers_every_tier_in_the_shipped_policy(self):
        from handoff.escalation.policy import Policy
        roster = Roster.from_config("config/roster.yaml")
        policy = Policy.from_config("config/policy.yaml")
        for rule in policy.rules.values():
            for tier in rule.ladder:
                self.assertTrue(roster.on_tier(tier), f"no responder on tier {tier}")

    def test_tier_with_no_responders_rejected(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        tmp.write("tiers:\n  - primary\n  - ghost\nresponders:\n  - id: a\n"
                  "    name: A\n    tier: primary\n")
        tmp.close()
        with self.assertRaises(ConfigError) as ctx:
            Roster.from_config(Path(tmp.name))
        self.assertIn("ghost", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
