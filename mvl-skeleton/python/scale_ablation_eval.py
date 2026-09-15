#!/usr/bin/env python3
"""一様スケールと各軸スケールの1反復比較を集計する。"""
import argparse
import csv
import json
import math
from pathlib import Path

import repair


RESULT_FIELDS = [
    "condition", "seed", "scale_mode", "machine_violations",
    "aspect_ratio_error_sum", "B1", "B4", "B5", "mean", "capture_dir",
]
DISTORTION_FIELDS = [
    "object_id", "object_class", "asset", "aspect_ratio_error",
    "worst_axis_ratio",
]


def _read_json(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"必要なファイルがありません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_result(iteration_dir, condition):
    iteration_dir = Path(iteration_dir).resolve()
    report = _read_json(iteration_dir / "capture" / "report.json")
    violations = _read_json(iteration_dir / "violations.json")
    scores = _read_json(iteration_dir / "scores.json")
    summary = _read_json(iteration_dir.parent / "best_summary.json")
    return {
        "condition": condition,
        "seed": report.get("scene_id", iteration_dir.parent.name),
        "scale_mode": report.get("scale_mode", "unknown"),
        "machine_violations": len(violations),
        "aspect_ratio_error_sum": summary.get("aspect_ratio_error_sum"),
        "B1": scores.get("B1"),
        "B4": scores.get("B4"),
        "B5": scores.get("B5"),
        "mean": scores.get("mean"),
        "capture_dir": str(iteration_dir / "capture"),
    }


def distortion_rows(reference_scene_path):
    reference_scene_path = Path(reference_scene_path).resolve()
    scene = _read_json(reference_scene_path)
    assets_dir = (reference_scene_path.parent /
                  scene.get("assets_dir", "assets")).resolve()
    dimensions = repair.load_asset_dimensions(assets_dir)
    rows = []
    seen = set()
    for obj in scene.get("objects", []):
        assets = [obj.get("asset"), *(obj.get("asset_variants") or [])]
        for asset in assets:
            if not asset or asset in seen:
                continue
            seen.add(asset)
            error = repair.aspect_ratio_error(
                obj.get("target_dimensions") or {}, dimensions.get(asset))
            if error is None:
                continue
            rows.append({
                "object_id": obj.get("id"),
                "object_class": obj.get("class"),
                "asset": asset,
                "aspect_ratio_error": error,
                "worst_axis_ratio": math.exp(error),
            })
    return sorted(rows, key=lambda row: row["aspect_ratio_error"])


def _write_csv(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _percentile(values, fraction):
    if not values:
        return None
    index = round((len(values) - 1) * fraction)
    return values[index]


def print_summary(rows, distortions):
    print("scale ablation: per_axis vs uniform")
    for row in rows:
        print(
            f"  {row['condition']:>8} {row['seed']}: "
            f"violations={row['machine_violations']} "
            f"aspect={row['aspect_ratio_error_sum']} "
            f"B1={row['B1']} B4={row['B4']} B5={row['B5']}"
        )
    values = [row["aspect_ratio_error"] for row in distortions]
    print(f"\ndistortion distribution: n={len(values)}")
    if values:
        print(
            "  "
            f"min={values[0]:.3f} "
            f"p50={_percentile(values, 0.50):.3f} "
            f"p75={_percentile(values, 0.75):.3f} "
            f"p90={_percentile(values, 0.90):.3f} "
            f"p95={_percentile(values, 0.95):.3f} "
            f"max={values[-1]:.3f}"
        )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-axis", nargs=3, required=True,
                        metavar=("SEED1", "SEED2", "SEED3"))
    parser.add_argument("--uniform", nargs=3, required=True,
                        metavar=("SEED1", "SEED2", "SEED3"))
    parser.add_argument("--reference-scene", required=True)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--distortion-csv", required=True)
    args = parser.parse_args(argv)

    rows = [load_result(path, "per_axis") for path in args.per_axis]
    rows += [load_result(path, "uniform") for path in args.uniform]
    distortions = distortion_rows(args.reference_scene)
    _write_csv(args.csv, RESULT_FIELDS, rows)
    _write_csv(args.distortion_csv, DISTORTION_FIELDS, distortions)
    print_summary(rows, distortions)
    print(f"\nresults CSV: {Path(args.csv).resolve()}")
    print(f"distortion CSV: {Path(args.distortion_csv).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
