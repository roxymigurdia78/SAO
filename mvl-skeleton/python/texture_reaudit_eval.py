#!/usr/bin/env python3
"""初回VLM予測を、v2人手監査の継ぎ目・反復ラベル別に再集計する。"""
import argparse
import csv
import json
from pathlib import Path

from texture_repetition_vlm_eval import evaluate_predictions, load_predictions


AXES = ("visible_seam", "unnatural_repetition", "quality_gate")


def load_reaudit_labels(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    labels = {}
    for row in rows:
        blind_id = (row.get("blind_id") or "").strip()
        seam = (row.get("visible_seam") or "").strip().lower()
        repetition = (row.get("unnatural_repetition") or "").strip().lower()
        acceptable = (row.get("acceptable") or "").strip().lower()
        if not blind_id or seam not in ("yes", "no") \
                or repetition not in ("yes", "no") \
                or acceptable not in ("yes", "no"):
            raise ValueError(f"v2ラベルが不正です: {row}")
        expected_acceptable = "yes" if seam == repetition == "no" else "no"
        if acceptable != expected_acceptable:
            raise ValueError(
                f"acceptableが2軸と矛盾しています: {blind_id}")
        if blind_id in labels:
            raise ValueError(f"blind_idが重複しています: {blind_id}")
        labels[blind_id] = {
            "visible_seam": seam,
            "unnatural_repetition": repetition,
            "quality_gate": "no" if acceptable == "yes" else "yes",
        }
    return labels


def evaluate_axes(predictions, labels):
    details = []
    metrics = {}
    for axis in AXES:
        binary_labels = {
            blind_id: "reject" if values[axis] == "yes" else "acceptable"
            for blind_id, values in labels.items()
        }
        rows, axis_metrics = evaluate_predictions(predictions, binary_labels)
        metrics[axis] = axis_metrics
        for row in rows:
            details.append({"axis": axis, **row})
    return details, metrics


def write_details(path, rows):
    fields = (
        "axis", "blind_id", "unnatural_repetition", "confidence", "detail",
        "visual_label", "outcome")
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def print_metrics(metrics):
    def percent(value):
        return "N/A" if value is None else f"{value:.1%}"

    for axis in AXES:
        row = metrics[axis]
        print(f"[{axis}] TP={row['tp']} FN={row['fn']} "
              f"FP={row['fp']} TN={row['tn']} / "
              f"検出率={percent(row['detection_rate'])} / "
              f"誤検出率={percent(row['false_positive_rate'])} / "
              f"正解率={percent(row['accuracy'])}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="v2人手監査によるVLM再集計")
    parser.add_argument("predictions_json")
    parser.add_argument("human_labels_v2_csv")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    predictions = load_predictions(args.predictions_json)
    labels = load_reaudit_labels(args.human_labels_v2_csv)
    details, metrics = evaluate_axes(predictions, labels)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_details(output_dir / "evaluation_v2.csv", details)
    (output_dir / "result_v2.json").write_text(
        json.dumps({
            "status": "post_hoc_adjudication_not_blind_holdout",
            "prediction_meaning": "initial VLM unnatural_repetition=true",
            "metrics_by_human_axis": metrics,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print_metrics(metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
