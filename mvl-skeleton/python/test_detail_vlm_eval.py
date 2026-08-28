#!/usr/bin/env python3
import csv
import unittest
from pathlib import Path

from detail_vlm_eval import aggregate_rows, evaluate_records, write_csv


class DetailVlmEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.violations = [
            {"type": "floating", "object_id": "a"},
            {"type": "penetration", "object_ids": ["b", "c"]},
            {"type": "scale", "object_id": "c"},
        ]
        self.audits = [
            {"object_id": "a", "status": "fail", "findings": [
                {"kind": "floating"}, {"kind": "orientation"}]},
            {"object_id": "b", "status": "fail", "findings": [
                {"kind": "penetration"}]},
            {"object_id": "c", "status": "pass", "findings": []},
            {"object_id": "d", "status": "fail", "findings": [
                {"kind": "floating"}, {"kind": "scale"},
                {"kind": "functional_relation"}]},
        ]

    def test_object_by_item_confusion_tables(self):
        rows = evaluate_records(self.violations, self.audits, "sample")
        floating = next(row for row in rows if row["item"] == "floating")
        penetration = next(row for row in rows if row["item"] == "penetration")
        self.assertEqual((1, 0, 1, 2), tuple(
            floating[key] for key in ("tp", "fn", "fp", "tn")))
        self.assertEqual((1, 1, 0, 2), tuple(
            penetration[key] for key in ("tp", "fn", "fp", "tn")))
        self.assertEqual(1.0, floating["detection_rate"])
        self.assertAlmostEqual(1 / 3, floating["false_positive_rate"])

    def test_scale_and_semantics_are_counted_without_confusion_labels(self):
        rows = evaluate_records(self.violations, self.audits, "sample")
        scale = next(row for row in rows if row["item"] == "scale")
        orientation = next(row for row in rows if row["item"] == "orientation")
        functional = next(
            row for row in rows if row["item"] == "functional_relation")
        self.assertEqual(1, scale["machine_positive_objects"])
        self.assertEqual(1, scale["vlm_positive_objects"])
        self.assertIsNone(scale["false_positive_rate"])
        self.assertEqual(1, orientation["vlm_findings"])
        self.assertEqual(1, functional["vlm_findings"])

    def test_aggregate_and_csv_output(self):
        detail = evaluate_records(self.violations, self.audits, "sample")
        total = aggregate_rows(detail)
        floating = next(row for row in total if row["item"] == "floating")
        combined = next(
            row for row in total if row["item"] == "floating+penetration")
        self.assertEqual("TOTAL", floating["scope"])
        self.assertEqual(4, floating["audited_objects"])
        self.assertEqual((2, 1, 1, 4), tuple(
            combined[key] for key in ("tp", "fn", "fp", "tn")))
        path = Path(__file__).with_name("_test_detail_vlm_eval.csv")
        try:
            write_csv(path, detail + total)
            with path.open(encoding="utf-8-sig", newline="") as handle:
                written = list(csv.DictReader(handle))
            self.assertEqual(11, len(written))
            self.assertEqual("confusion", written[0]["section"])
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
