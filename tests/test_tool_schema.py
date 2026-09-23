import unittest

from handoff.core.errors import ValidationError
from handoff.tools.schema import Field, validate


class TestField(unittest.TestCase):
    def test_required_missing_raises(self):
        with self.assertRaises(ValidationError) as ctx:
            validate("t", (Field("a", str),), {})
        self.assertIn("t.a", str(ctx.exception))

    def test_optional_missing_takes_default(self):
        out = validate("t", (Field("a", int, required=False, default=7),), {})
        self.assertEqual(out["a"], 7)

    def test_wrong_type_raises(self):
        with self.assertRaises(ValidationError):
            validate("t", (Field("a", int),), {"a": "3"})

    def test_bool_is_not_an_int(self):
        with self.assertRaises(ValidationError):
            validate("t", (Field("a", int),), {"a": True})

    def test_int_widens_to_float(self):
        self.assertEqual(validate("t", (Field("a", float),), {"a": 3})["a"], 3.0)

    def test_choices_enforced(self):
        fields = (Field("a", str, choices=("x", "y")),)
        self.assertEqual(validate("t", fields, {"a": "x"})["a"], "x")
        with self.assertRaises(ValidationError):
            validate("t", fields, {"a": "z"})

    def test_bounds_enforced(self):
        fields = (Field("n", int, minimum=1, maximum=10),)
        self.assertEqual(validate("t", fields, {"n": 5})["n"], 5)
        with self.assertRaises(ValidationError):
            validate("t", fields, {"n": 0})
        with self.assertRaises(ValidationError):
            validate("t", fields, {"n": 11})

    def test_unknown_argument_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate("t", (Field("a", str),), {"a": "x", "typo": 1})
        self.assertIn("unknown argument", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
