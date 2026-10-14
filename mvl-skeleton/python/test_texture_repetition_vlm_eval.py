#!/usr/bin/env python3
import unittest
from pathlib import Path

from texture_repetition_vlm_eval import (
    ensure_run_config, evaluate_predictions, load_predictions, save_predictions,
    validate_prediction,
)


class TextureRepetitionVlmEvalTests(unittest.TestCase):
    def test_validate_prediction_normalizes_valid_response(self):
        result = validate_prediction({
            "unnatural_repetition": True,
            "confidence": 1,
            "detail": " 中央に縦列が見える。 ",
        })
        self.assertIs(result["unnatural_repetition"], True)
        self.assertEqual(1.0, result["confidence"])
        self.assertEqual("中央に縦列が見える。", result["detail"])

    def test_validate_prediction_rejects_string_boolean_and_bad_confidence(self):
        with self.assertRaises(ValueError):
            validate_prediction({
                "unnatural_repetition": "true", "confidence": 0.8,
                "detail": "根拠"})
        with self.assertRaises(ValueError):
            validate_prediction({
                "unnatural_repetition": True, "confidence": 1.1,
                "detail": "根拠"})

    def test_confusion_metrics_use_reject_as_positive(self):
        predictions = [
            {"blind_id": "B001", "unnatural_repetition": True,
             "confidence": 0.9, "detail": "a"},
            {"blind_id": "B002", "unnatural_repetition": False,
             "confidence": 0.8, "detail": "b"},
            {"blind_id": "B003", "unnatural_repetition": False,
             "confidence": 0.7, "detail": "c"},
            {"blind_id": "B004", "unnatural_repetition": True,
             "confidence": 0.6, "detail": "d"},
        ]
        labels = {
            "B001": "reject", "B002": "reject",
            "B003": "acceptable", "B004": "acceptable",
        }
        rows, metrics = evaluate_predictions(predictions, labels)
        self.assertEqual((1, 1, 1, 1), tuple(
            metrics[key] for key in ("tp", "fn", "fp", "tn")))
        self.assertEqual(0.5, metrics["detection_rate"])
        self.assertEqual(0.5, metrics["false_positive_rate"])
        self.assertEqual(["TP", "FN", "TN", "FP"],
                         [row["outcome"] for row in rows])

    def test_predictions_round_trip(self):
        predictions = [{
            "blind_id": "B001", "unnatural_repetition": False,
            "confidence": 0.75, "detail": "自然に連続する。",
        }]
        path = Path(__file__).with_name("_test_texture_predictions.json")
        try:
            save_predictions(path, predictions)
            self.assertEqual(predictions, load_predictions(path))
        finally:
            path.unlink(missing_ok=True)

    def test_evaluation_rejects_mismatched_ids(self):
        prediction = [{
            "blind_id": "B001", "unnatural_repetition": False,
            "confidence": 0.75, "detail": "自然",
        }]
        with self.assertRaises(ValueError):
            evaluate_predictions(prediction, {"B002": "acceptable"})

    def test_run_config_prevents_mixed_prompt_or_model(self):
        path = Path(__file__).with_name("_test_texture_run_config.json")
        try:
            first = ensure_run_config(path, "frozen prompt", "model-a")
            self.assertEqual(first, ensure_run_config(
                path, "frozen prompt", "model-a"))
            with self.assertRaises(ValueError):
                ensure_run_config(path, "changed prompt", "model-a")
            with self.assertRaises(ValueError):
                ensure_run_config(path, "frozen prompt", "model-b")
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
