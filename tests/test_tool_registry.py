import unittest

from handoff.core.errors import UnknownToolError
from handoff.core.types import Risk
from handoff.tools.registry import Tool, ToolRegistry


def tool(name, risk=Risk.LOW, fallback=None):
    return Tool(name=name, description="", risk=risk, safe_fallback=fallback)


class TestRegistry(unittest.TestCase):
    def test_register_and_get(self):
        r = ToolRegistry()
        r.register(tool("a"))
        self.assertTrue(r.has("a"))
        self.assertEqual(r.get("a").name, "a")

    def test_duplicate_registration_raises(self):
        r = ToolRegistry()
        r.register(tool("a"))
        with self.assertRaises(ValueError):
            r.register(tool("a"))

    def test_unknown_tool_raises(self):
        with self.assertRaises(UnknownToolError):
            ToolRegistry().get("nope")

    def test_at_or_above_filters_by_rank(self):
        r = ToolRegistry()
        r.register(tool("lo", Risk.LOW))
        r.register(tool("hi", Risk.HIGH))
        r.register(tool("crit", Risk.CRITICAL))
        self.assertEqual({t.name for t in r.at_or_above(Risk.HIGH)}, {"hi", "crit"})


class TestFallbackIntegrity(unittest.TestCase):
    def test_clean_registry_has_no_problems(self):
        r = ToolRegistry()
        r.register(tool("safe", Risk.LOW))
        r.register(tool("risky", Risk.HIGH, fallback="safe"))
        self.assertEqual(r.check_fallbacks(), [])

    def test_missing_fallback_reported(self):
        r = ToolRegistry()
        r.register(tool("risky", Risk.HIGH, fallback="ghost"))
        self.assertIn("not registered", r.check_fallbacks()[0])

    def test_self_referential_fallback_reported(self):
        r = ToolRegistry()
        r.register(tool("loop", Risk.HIGH, fallback="loop"))
        self.assertIn("itself", r.check_fallbacks()[0])

    def test_fallback_must_be_strictly_lower_risk(self):
        r = ToolRegistry()
        r.register(tool("a", Risk.HIGH))
        r.register(tool("b", Risk.HIGH, fallback="a"))
        self.assertIn("not lower risk", r.check_fallbacks()[0])

    def test_all_problems_reported_not_just_the_first(self):
        r = ToolRegistry()
        r.register(tool("x", Risk.HIGH, fallback="ghost"))
        r.register(tool("y", Risk.HIGH, fallback="y"))
        self.assertEqual(len(r.check_fallbacks()), 2)


if __name__ == "__main__":
    unittest.main()
