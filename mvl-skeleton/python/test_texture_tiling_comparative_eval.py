#!/usr/bin/env python3
import unittest

from texture_tiling_comparative_eval import validate_prediction


class TextureTilingComparativeEvalTests(unittest.TestCase):
    def test_validates_consistent_binary_response(self):
        result = validate_prediction({
            "unnatural_tiling": True,
            "confidence": 0.9,
            "closer_to": "unacceptable",
            "detail": "不採用参照に近い。",
        })
        self.assertIs(result["unnatural_tiling"], True)

    def test_rejects_inconsistent_closer_to(self):
        with self.assertRaises(ValueError):
            validate_prediction({
                "unnatural_tiling": True,
                "confidence": 0.9,
                "closer_to": "acceptable",
                "detail": "矛盾",
            })


if __name__ == "__main__":
    unittest.main()
