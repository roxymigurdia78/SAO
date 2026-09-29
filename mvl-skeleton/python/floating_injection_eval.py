#!/usr/bin/env python3
"""浮遊欠陥注入ランを集計する。"""
import argparse
import csv
import json
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_iteration(iteration_dir, scope):
    iteration_dir = Path(iteration_dir)
    scene = load_json(iteration_dir / "scene.json")
    violations = load_json(iteration_dir / "violations.json")
    audits = load_json(iteration_dir / "detail_audit.json")
    injection = scene.get("evaluation_injection", {})
    if injection.get("kind") != "floating":
        raise ValueError(f"浮遊欠陥注入シーンではない: {iteration_dir}")

    universe = {a.get("object_id") for a in audits if a.get("object_id")}
    truth = {item.get("object_id") for item in injection.get("objects", [])
             if item.get("object_id")} & universe
    machine_positive = {
        v.get("object_id") for v in violations
        if v.get("type") == "floating" and v.get("object_id")
    }
    missing_labels = truth - machine_positive
    if missing_labels:
        raise ValueError(f"Unity実測で浮遊正解にならなかった: {sorted(missing_labels)}")
    predicted = {
        a.get("object_id") for a in audits
        if any(f.get("kind") == "floating" for f in a.get("findings", []))
    } & universe
    negatives = universe - machine_positive
    invalid = sum(bool(a.get("status") == "uncertain" and a.get("error"))
                  for a in audits)
    tp = len(truth & predicted)
    fn = len(truth - predicted)
    fp = len(negatives & predicted)
    tn = len(negatives - predicted)
    return {
        "scope": scope,
        "injected_positives": len(truth),
        "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "detection_rate": tp / (tp + fn) if tp + fn else None,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "invalid_after_retries": invalid,
        "extra_machine_positives": len(machine_positive - truth),
    }


def percent(value):
    return "N/A" if value is None else f"{value:.1%}"


def main():
    parser = argparse.ArgumentParser(description="浮遊欠陥注入3シードの集計")
    parser.add_argument("iteration_dirs", nargs="+")
    parser.add_argument("--csv", required=True)
    args = parser.parse_args()

    rows = [evaluate_iteration(path, f"seed{index}")
            for index, path in enumerate(args.iteration_dirs, 1)]
    total_keys = ("injected_positives", "tp", "fn", "fp", "tn",
                  "invalid_after_retries", "extra_machine_positives")
    total = {key: sum(row[key] for row in rows) for key in total_keys}
    total["scope"] = "TOTAL"
    total["detection_rate"] = (
        total["tp"] / (total["tp"] + total["fn"]) if total["tp"] + total["fn"] else None)
    total["false_positive_rate"] = (
        total["fp"] / (total["fp"] + total["tn"]) if total["fp"] + total["tn"] else None)
    rows.append(total)

    output = Path(args.csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print("floating defect-injection evaluation")
    for row in rows:
        print(f"{row['scope']}: tp={row['tp']} fn={row['fn']} "
              f"fp={row['fp']} tn={row['tn']} "
              f"detection={percent(row['detection_rate'])} "
              f"false_positive={percent(row['false_positive_rate'])} "
              f"invalid={row['invalid_after_retries']} "
              f"extra_machine_positive={row['extra_machine_positives']}")
    print(f"CSV: {output.resolve()}")


if __name__ == "__main__":
    main()
