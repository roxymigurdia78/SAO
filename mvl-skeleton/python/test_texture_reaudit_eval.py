#!/usr/bin/env python3
import unittest

from texture_reaudit_eval import evaluate_axes


class TextureReauditEvalTests(unittest.TestCase):
    def test_axes_are_evaluated_independently(self):
        predictions = [
            {"blind_id": "B001", "unnatural_repetition": True,
             "confidence": 0.9, "detail": "x"},
            {"blind_id": "B002", "unnatural_repetition": False,
             "confidence": 0.8, "detail": "y"},
        ]
        labels = {
            "B001": {"visible_seam": "yes", "unnatural_repetition": "no",
                     "quality_gate": "yes"},
            "B002": {"visible_seam": "no", "unnatural_repetition": "no",
                     "quality_gate": "no"},
        }
        _, metrics = evaluate_axes(predictions, labels)
        self.assertEqual((1, 0, 0, 1), tuple(
            metrics["visible_seam"][key]
            for key in ("tp", "fn", "fp", "tn")))
        self.assertEqual((0, 0, 1, 1), tuple(
            metrics["unnatural_repetition"][key]
            for key in ("tp", "fn", "fp", "tn")))


if __name__ == "__main__":
    unittest.main()
