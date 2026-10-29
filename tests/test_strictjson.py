# DEVELOPED BY CARROTSTUDIO software house
"""Strict JSON, the one reader for everything that comes from outside."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
import sharing
import strictjson


class TestStrictJson(unittest.TestCase):
    def test_ordinary_json_reads_as_usual(self):
        self.assertEqual(
            strictjson.loads('{"a": [1, 2.5, "x", null, true]}'), {"a": [1, 2.5, "x", None, True]}
        )

    def test_a_key_written_twice_is_refused_at_any_depth(self):
        for text in ('{"text": "a", "text": "b"}', '{"x": {"k": 1, "k": 2}}', '[{"k": 1, "k": 1}]'):
            with self.subTest(text), self.assertRaises(ValueError):
                strictjson.loads(text)

    def test_nan_and_infinity_are_not_json(self):
        for text in ('{"n": NaN}', '{"n": Infinity}', "[-Infinity]"):
            with self.subTest(text), self.assertRaises(ValueError):
                strictjson.loads(text)

    def test_nesting_too_deep_is_a_plain_refusal(self):
        # Python 3.9 to 3.13 give up on deep nesting with a RecursionError (3.14 reads it):
        # raised here on purpose, so the test means the same on every version.
        with mock.patch.object(json, "loads", side_effect=RecursionError):
            with self.assertRaises(ValueError):
                strictjson.loads("[]")
            with self.assertRaises(ValueError):  # the share list, read by the setup page
                sharing.check("[]")


if __name__ == "__main__":
    unittest.main()
