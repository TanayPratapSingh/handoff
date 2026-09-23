import unittest

from handoff.core.errors import ConfigError
from handoff.core.miniyaml import loads


class TestScalars(unittest.TestCase):
    def test_types(self):
        doc = loads("i: 3\nf: 0.25\nt: true\nf2: False\nn: null\ns: plain words")
        self.assertEqual(doc["i"], 3)
        self.assertEqual(doc["f"], 0.25)
        self.assertIs(doc["t"], True)
        self.assertIs(doc["f2"], False)
        self.assertIsNone(doc["n"])
        self.assertEqual(doc["s"], "plain words")

    def test_quotes_preserve_literal(self):
        doc = loads('a: "true"\nb: \'3\'')
        self.assertEqual(doc["a"], "true")
        self.assertEqual(doc["b"], "3")

    def test_inline_list(self):
        self.assertEqual(loads("k: [a, b, 3]")["k"], ["a", "b", 3])
        self.assertEqual(loads("k: []")["k"], [])


class TestStructure(unittest.TestCase):
    def test_nested_maps(self):
        doc = loads("a:\n  b:\n    c: 1")
        self.assertEqual(doc["a"]["b"]["c"], 1)

    def test_list_of_maps_with_continuation(self):
        doc = loads("people:\n  - name: ana\n    tier: primary\n  - name: bo\n    tier: backup")
        self.assertEqual(len(doc["people"]), 2)
        self.assertEqual(doc["people"][0], {"name": "ana", "tier": "primary"})
        self.assertEqual(doc["people"][1], {"name": "bo", "tier": "backup"})

    def test_empty_document(self):
        self.assertEqual(loads(""), {})
        self.assertEqual(loads("# only a comment"), {})

    def test_key_with_no_value_is_none(self):
        doc = loads("a:\nb: 2")
        self.assertIsNone(doc["a"])
        self.assertEqual(doc["b"], 2)


class TestComments(unittest.TestCase):
    def test_trailing_comment_stripped(self):
        self.assertEqual(loads("a: 1  # why")["a"], 1)

    def test_hash_inside_quotes_survives(self):
        self.assertEqual(loads('a: "tag #1"')["a"], "tag #1")


class TestRejections(unittest.TestCase):
    def test_anchor_rejected(self):
        with self.assertRaises(ConfigError):
            loads("a: 1\n&anchor b: 2")

    def test_tab_indent_rejected(self):
        with self.assertRaises(ConfigError):
            loads("a:\n\tb: 1")

    def test_duplicate_key_rejected(self):
        with self.assertRaises(ConfigError):
            loads("a: 1\na: 2")

    def test_missing_colon_rejected(self):
        with self.assertRaises(ConfigError):
            loads("just a bare line")


if __name__ == "__main__":
    unittest.main()
