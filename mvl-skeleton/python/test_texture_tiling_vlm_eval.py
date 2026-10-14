#!/usr/bin/env python3
import unittest
from pathlib import Path

from texture_tiling_vlm_eval import (
    DEFAULT_PROMPT, evaluate_axes, validate_prediction,
)


class TextureTilingVlmEvalTests(unittest.TestCase):
    def test_default_prompt_contains_a_valid_json_shape(self):
        prompt = Path(DEFAULT_PROMPT).read_text(encoding="utf-8")
        self.assertIn('"visible_seam": false', prompt)
        self.assertIn('"unnatural_repetition": false', prompt)
        self.assertIn('必ず `{` で始まり `}` で終わる', prompt)

    def test_validates_two_axes_independently(self):
        result = validate_prediction({
            "visible_seam": True,
            "visible_seam_confidence": 0.9,
            "visible_seam_detail": "中央に水平線が見える。",
            "unnatural_repetition": False,
            "unnatural_repetition_confidence": 0.8,
            "unnatural_repetition_detail": "特徴的な模様の周期は目立たない。",
        })
        self.assertIs(result["visible_seam"], True)
        self.assertIs(result["unnatural_repetition"], False)

    def test_rejects_non_boolean_axis(self):
        with self.assertRaises(ValueError):
            validate_prediction({
                "visible_seam": "true",
                "visible_seam_confidence": 0.9,
                "visible_seam_detail": "x",
                "unnatural_repetition": False,
                "unnatural_repetition_confidence": 0.8,
                "unnatural_repetition_detail": "y",
            })

    def test_evaluates_each_axis_with_its_own_prediction(self):
        predictions = [{
            "blind_id": "B001",
            "visible_seam": True,
            "visible_seam_confidence": 0.9,
            "visible_seam_detail": "seam",
            "unnatural_repetition": False,
            "unnatural_repetition_confidence": 0.8,
            "unnatural_repetition_detail": "repeat",
        }]
        labels = {"B001": {
            "visible_seam": "yes", "unnatural_repetition": "no",
            "quality_gate": "yes"}}
        _, metrics = evaluate_axes(predictions, labels)
        self.assertEqual(1, metrics["visible_seam"]["tp"])
        self.assertEqual(1, metrics["unnatural_repetition"]["tn"])


if __name__ == "__main__":
    unittest.main()
