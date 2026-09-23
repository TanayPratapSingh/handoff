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
        doc = loads("a: \"true\"\nb: '3'")
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


class TestBlockScalars(unittest.TestCase):
    def test_folded_joins_lines_with_spaces(self):
        doc = loads("k: >\n  one two\n  three\nafter: 1")
        self.assertEqual(doc["k"], "one two three")
        self.assertEqual(doc["after"], 1)

    def test_folded_treats_a_blank_line_as_a_paragraph_break(self):
        doc = loads("k: >\n  first para\n\n  second para")
        self.assertEqual(doc["k"], "first para\nsecond para")

    def test_literal_keeps_line_breaks(self):
        doc = loads("k: |\n  one\n  two")
        self.assertEqual(doc["k"], "one\ntwo")

    def test_strip_chomping_removes_the_trailing_newline(self):
        self.assertEqual(loads("k: >-\n  text")["k"], "text")

    def test_keep_chomping_adds_one(self):
        self.assertEqual(loads("k: |+\n  text")["k"], "text\n")

    def test_a_hash_inside_a_block_is_literal_text(self):
        """A # in a block scalar is a hash, not a comment.

        The scanner resolves blocks before comment stripping for exactly
        this reason. Getting it wrong silently truncates prose in the
        scenario files, where every case carries a written rationale.
        """
        self.assertEqual(loads("k: >\n  see issue #42 for why")["k"], "see issue #42 for why")

    def test_a_colon_inside_a_block_does_not_start_a_key(self):
        self.assertEqual(loads("k: >\n  note: this is prose")["k"], "note: this is prose")

    def test_block_scalar_inside_a_nested_map(self):
        doc = loads("outer:\n  inner: >\n    folded text\n  other: 2")
        self.assertEqual(doc["outer"]["inner"], "folded text")
        self.assertEqual(doc["outer"]["other"], 2)


class TestNestingInsideListItems(unittest.TestCase):
    def test_a_nested_map_inside_a_list_item_keeps_its_shape(self):
        """Continuation lines keep their own indentation.

        Rewriting every continuation line to one synthetic level flattens
        nested maps, which silently emptied modified_args in the scenario
        files and produced an approval with no edits rather than an error.
        """
        doc = loads(
            "decisions:\n"
            "  - decision: modify\n"
            "    args:\n"
            "      service: checkout\n"
            "      replicas: 9\n"
            "  - decision: approve\n"
        )
        self.assertEqual(doc["decisions"][0]["args"], {"service": "checkout", "replicas": 9})
        self.assertEqual(doc["decisions"][1], {"decision": "approve"})

    def test_a_nested_list_inside_a_list_item(self):
        doc = loads("outer:\n  - name: a\n    tags:\n      - x\n      - y\n")
        self.assertEqual(doc["outer"][0]["tags"], ["x", "y"])

    def test_a_block_scalar_inside_a_list_item(self):
        doc = loads("outer:\n  - name: a\n    why: >\n      folded reason\n")
        self.assertEqual(doc["outer"][0]["why"], "folded reason")
