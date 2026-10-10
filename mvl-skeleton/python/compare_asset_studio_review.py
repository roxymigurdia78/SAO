"""目視レビュー結果とAsset Studioの材質指標を照合する。

このスクリプトは分布とクラス内順位だけを出力し、閾値や合否判定は行わない。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from skimage.filters import laplace

from analyze_asset_studio import analyze_directory, eroded_mask, normalized_crop


VERSION_PATTERN = re.compile(r"^(?P<class_name>.+)_v(?P<version>[123])$")
METRICS = (
    "laplacian_median",
    "glcm_contrast_median",
    "input_laplacian_ratio",
)
LABEL_FIELDS = ("detail_lost", "flat_surface")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def require_unique(rows: list[dict[str, str]], field: str, source: Path) -> None:
    values = [row[field] for row in rows]
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"{source}: {field} が重複しています: {duplicates}")


def normalized_label(value: str) -> str:
    value = value.strip().lower()
    return value if value in {"yes", "no"} else ""


def find_label_column(fieldnames: list[str], prefix: str) -> str:
    matches = [name for name in fieldnames if name == prefix or name.startswith(prefix + "(")]
    if len(matches) != 1:
        raise ValueError(f"{prefix} 列を一意に特定できません: {fieldnames}")
    return matches[0]


def load_review_rows(labels_path: Path, key_path: Path) -> list[dict[str, str]]:
    labels = read_csv(labels_path)
    keys = read_csv(key_path)
    if not labels or not keys:
        raise ValueError("レビューCSVまたは対応表が空です。")
    require_unique(labels, "anon_id", labels_path)
    require_unique(keys, "anon_id", key_path)

    detail_column = find_label_column(list(labels[0]), "detail_lost")
    flat_column = find_label_column(list(labels[0]), "flat_surface")
    labels_by_id = {row["anon_id"]: row for row in labels}
    result: list[dict[str, str]] = []
    for key in keys:
        label = labels_by_id.get(key["anon_id"])
        if label is None:
            raise ValueError(f"ラベルがありません: {key['anon_id']}")
        if label.get("class", "").strip() != key["class"].strip():
            raise ValueError(f"class が対応表と不一致です: {key['anon_id']}")
        result.append(
            {
                "anon_id": key["anon_id"],
                "asset": key["asset"],
                "class": key["class"],
                "is_example": key["is_example"].strip().lower(),
                "detail_lost": normalized_label(label.get(detail_column, "")),
                "flat_surface": normalized_label(label.get(flat_column, "")),
            }
        )
    return result


def verify_report(report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if report.get("success") is not True or report.get("error"):
        raise ValueError(f"撮影reportが成功状態ではありません: {report.get('error')!r}")
    reflection = str(report.get("reflection", ""))
    expected_terms = ("uniform", "0.5", "intensity 0.35")
    if not all(term in reflection.lower() for term in expected_terms):
        raise ValueError(f"環境反射が凍結条件と一致しません: {reflection!r}")
    if len(report.get("assets", [])) != 48:
        raise ValueError(f"report.json のアセット数が48ではありません: {len(report.get('assets', []))}")
    return report


def input_laplacian(
    path: Path,
    white_distance: float,
    erode_pixels: int,
    size: int,
) -> float:
    with Image.open(path) as image:
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    rgb = rgba[:, :, :3].astype(np.float32) / 255.0
    alpha = rgba[:, :, 3]
    if np.any(alpha < 255):
        mask = alpha >= 128
    else:
        white = np.ones(3, dtype=np.float32)
        mask = np.linalg.norm(rgb - white, axis=2) > white_distance
    mask = eroded_mask(mask, erode_pixels)
    normalized_rgb, normalized_mask = normalized_crop(rgb, mask, size)
    gray = np.tensordot(
        normalized_rgb,
        np.array([0.2126, 0.7152, 0.0722], dtype=np.float32),
        axes=([2], [0]),
    ).astype(np.float32)
    return float(np.var(laplace(gray)[normalized_mask]))


def aggregate_views(view_rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in view_rows:
        grouped.setdefault(str(row["asset"]), []).append(row)
    result: dict[str, dict[str, float]] = {}
    for asset, rows in grouped.items():
        if len(rows) != 8:
            raise ValueError(f"{asset}: 8方位ではありません ({len(rows)})")
        result[asset] = {
            "laplacian_median": float(np.median([float(row["laplacian_var"]) for row in rows])),
            "glcm_contrast_median": float(np.median([float(row["glcm_contrast"]) for row in rows])),
        }
    return result


def attach_input_ratios(
    metrics: dict[str, dict[str, float]],
    input_map_path: Path,
    repo_root: Path,
    white_distance: float,
    erode_pixels: int,
    size: int,
) -> None:
    input_rows = read_csv(input_map_path)
    require_unique(input_rows, "asset", input_map_path)
    paths = {row["asset"]: row["input_image"] for row in input_rows}
    for asset, values in metrics.items():
        relative = paths.get(asset, "").strip()
        if not relative:
            raise ValueError(f"入力画像の対応がありません: {asset}")
        input_path = (repo_root / relative).resolve()
        if not input_path.is_file():
            raise FileNotFoundError(f"入力画像がありません: {input_path}")
        source_laplacian = input_laplacian(
            input_path, white_distance, erode_pixels, size
        )
        if source_laplacian <= 0.0:
            raise ValueError(f"入力画像のLaplacianが0以下です: {asset}")
        values["input_laplacian"] = source_laplacian
        values["input_laplacian_ratio"] = values["laplacian_median"] / source_laplacian


def class_rankings(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], int], set[tuple[str, str]]]:
    by_class: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_class.setdefault(str(row["class"]), []).append(row)

    table: list[dict[str, Any]] = []
    ranks: dict[tuple[str, str], int] = {}
    lowest: set[tuple[str, str]] = set()
    for class_name, class_rows in sorted(by_class.items()):
        if len(class_rows) != 3:
            raise ValueError(f"{class_name}: クラス内アセット数が3ではありません ({len(class_rows)})")
        for metric in METRICS:
            ordered = sorted(class_rows, key=lambda row: (-float(row[metric]), str(row["asset"])))
            output: dict[str, Any] = {"class": class_name, "metric": metric}
            minimum = min(float(row[metric]) for row in class_rows)
            for index, row in enumerate(ordered, start=1):
                ranks[(str(row["asset"]), metric)] = index
                if np.isclose(float(row[metric]), minimum, rtol=1e-12, atol=1e-15):
                    lowest.add((str(row["asset"]), metric))
                slot = ("best", "middle", "lowest")[index - 1]
                output[f"{slot}_asset"] = row["asset"]
                output[f"{slot}_value"] = round(float(row[metric]), 10)
            table.append(output)
    return table, ranks, lowest


def distribution(values: list[float]) -> dict[str, Any]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "n": int(array.size),
        "minimum": round(float(np.min(array)), 10),
        "q1": round(float(np.quantile(array, 0.25)), 10),
        "median": round(float(np.median(array)), 10),
        "q3": round(float(np.quantile(array, 0.75)), 10),
        "maximum": round(float(np.max(array)), 10),
    }


def build_summaries(
    non_example_rows: list[dict[str, Any]],
    ranks: dict[tuple[str, str], int],
    lowest: set[tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lowest_counts: list[dict[str, Any]] = []
    distributions: list[dict[str, Any]] = []
    for label_field in LABEL_FIELDS:
        for metric in METRICS:
            yes_rows = [row for row in non_example_rows if row[label_field] == "yes"]
            count = sum((str(row["asset"]), metric) in lowest for row in yes_rows)
            n = len(yes_rows)
            lowest_counts.append(
                {
                    "label": label_field,
                    "metric": metric,
                    "lowest_count": count,
                    "yes_count": n,
                    "fraction": f"{count} / {n}",
                    "chance_expectation": round(n / 3.0, 6),
                }
            )
            for label_value in ("yes", "no"):
                selected = [row for row in non_example_rows if row[label_field] == label_value]
                if not selected:
                    continue
                if metric == "input_laplacian_ratio":
                    values = [float(row[metric]) for row in selected]
                    measure = "input_laplacian_ratio"
                else:
                    values = [float(ranks[(str(row["asset"]), metric)]) for row in selected]
                    measure = "class_rank_1_best_3_lowest"
                distributions.append(
                    {
                        "label": label_field,
                        "label_value": label_value,
                        "metric": metric,
                        "measure": measure,
                        **distribution(values),
                    }
                )
    return lowest_counts, distributions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="目視レビューとAsset Studio材質指標を閾値なしで照合する"
    )
    parser.add_argument("capture_root", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("key", type=Path)
    parser.add_argument("input_map", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--white-distance", type=float, default=0.08)
    parser.add_argument("--erode-pixels", type=int, default=4)
    parser.add_argument("--size", type=int, default=256)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    capture_root = args.capture_root.resolve()
    labels_path = args.labels.resolve()
    key_path = args.key.resolve()
    input_map_path = args.input_map.resolve()
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir.resolve()

    report = verify_report(capture_root / "report.json")
    review_rows = load_review_rows(labels_path, key_path)
    view_csv = output_dir / "studio_material_view_metrics_20260930.csv"
    view_rows = analyze_directory(
        capture_root,
        view_csv,
        erode_pixels=args.erode_pixels,
        size=args.size,
    )
    metrics = aggregate_views(view_rows)
    attach_input_ratios(
        metrics,
        input_map_path,
        repo_root,
        args.white_distance,
        args.erode_pixels,
        args.size,
    )

    all_rows: list[dict[str, Any]] = []
    for review in review_rows:
        asset = review["asset"]
        if asset not in metrics:
            raise ValueError(f"撮影指標がありません: {asset}")
        match = VERSION_PATTERN.match(asset)
        if match is None or match.group("class_name") != review["class"]:
            raise ValueError(f"asset名とclassが一致しません: {asset}, {review['class']}")
        all_rows.append({**review, **metrics[asset]})
    if len(all_rows) != 48:
        raise ValueError(f"対応後のアセット数が48ではありません: {len(all_rows)}")

    rank_table, ranks, lowest = class_rankings(all_rows)
    non_example_rows = [row for row in all_rows if row["is_example"] != "yes"]
    asset_rows = [
        {
            "asset": row["asset"],
            "class": row["class"],
            "laplacian_median": round(float(row["laplacian_median"]), 10),
            "glcm_contrast_median": round(float(row["glcm_contrast_median"]), 10),
            "input_laplacian_ratio": round(float(row["input_laplacian_ratio"]), 10),
            "detail_lost": row["detail_lost"],
            "flat_surface": row["flat_surface"],
        }
        for row in non_example_rows
    ]
    lowest_counts, distributions = build_summaries(non_example_rows, ranks, lowest)

    output_dir.mkdir(parents=True, exist_ok=True)
    asset_table_path = output_dir / "studio_material_asset_table_20260930.csv"
    rank_table_path = output_dir / "studio_material_class_ranks_20260930.csv"
    counts_path = output_dir / "studio_material_lowest_counts_20260930.csv"
    distributions_path = output_dir / "studio_material_label_distributions_20260930.csv"
    write_csv(asset_table_path, list(asset_rows[0]), asset_rows)
    write_csv(rank_table_path, list(rank_table[0]), rank_table)
    write_csv(counts_path, list(lowest_counts[0]), lowest_counts)
    write_csv(distributions_path, list(distributions[0]), distributions)

    labels_sha256 = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    result = {
        "capture_root": str(capture_root),
        "labels": str(labels_path),
        "labels_sha256": labels_sha256,
        "examples_excluded": sum(row["is_example"] == "yes" for row in all_rows),
        "assets_aggregated": len(non_example_rows),
        "reflection": report["reflection"],
        "normalization_size": args.size,
        "mask_erosion_pixels": args.erode_pixels,
        "input_white_distance": args.white_distance,
        "lowest_counts": lowest_counts,
        "distributions": distributions,
    }
    result_path = output_dir / "studio_material_comparison_result_20260930.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("環境反射:", report["reflection"])
    print(f"集計: {len(non_example_rows)} assets / 練習用除外: {result['examples_excluded']}")
    print(f"labels SHA-256: {labels_sha256}")
    print("\nクラス内最下位（yesラベルのみ）")
    for row in lowest_counts:
        print(
            f"[{row['label']}] {row['metric']}: {row['fraction']} "
            f"(偶然期待値 {row['yes_count']}/3 = {row['chance_expectation']})"
        )
    print("\nyes/no分布")
    for row in distributions:
        print(
            f"[{row['label']}={row['label_value']}] {row['metric']} "
            f"{row['measure']}: n={row['n']} median={row['median']} "
            f"IQR=[{row['q1']}, {row['q3']}] range=[{row['minimum']}, {row['maximum']}]"
        )
    print("\n出力:")
    for path in (
        asset_table_path,
        rank_table_path,
        counts_path,
        distributions_path,
        result_path,
    ):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
