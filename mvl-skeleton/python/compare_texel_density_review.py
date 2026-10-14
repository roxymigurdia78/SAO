"""テクセル密度と凍結済み目視レビューを閾値なしで照合する。

クラス内v1/v2/v3順位を使い、物体の実寸差を統制する。練習用4件は順位の
母集団には含めるが、目視ラベル集計から除外する。既存材質指標の確定済み
集計は再計算せず、比較表へそのまま併記する。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from compare_asset_studio_review import (
    distribution,
    load_review_rows,
    read_csv,
    require_unique,
    write_csv,
)


VERSION_PATTERN = re.compile(r"^(?P<class_name>.+)_v(?P<version>[123])$")
TEXEL_METRICS = ("weighted_median_px_per_m", "weighted_p10_px_per_m")
LABEL_FIELDS = ("detail_lost", "flat_surface")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_texel_rows(path: Path) -> list[dict[str, Any]]:
    rows = read_csv(path)
    if len(rows) != 48:
        raise ValueError(f"テクセル密度CSVが48件ではありません: {len(rows)}")
    require_unique(rows, "asset", path)
    result: list[dict[str, Any]] = []
    for row in rows:
        asset = row["asset"].strip()
        class_name = row["class"].strip()
        match = VERSION_PATTERN.match(asset)
        if match is None or match.group("class_name") != class_name:
            raise ValueError(f"asset名とclassが一致しません: {asset}, {class_name}")
        parsed: dict[str, Any] = {
            "asset": asset,
            "class": class_name,
            "variant": int(row["variant"]),
        }
        for metric in TEXEL_METRICS:
            value = float(row[metric])
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"{asset}: {metric} が不正です: {row[metric]!r}")
            parsed[metric] = value
        parsed["basecolor_mapped_area_fraction"] = float(
            row["basecolor_mapped_area_fraction"]
        )
        parsed["degenerate_triangle_count"] = int(row["degenerate_triangle_count"])
        result.append(parsed)
    return result


def attach_review(
    texel_rows: list[dict[str, Any]], review_rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    review_by_asset = {row["asset"]: row for row in review_rows}
    if len(review_by_asset) != 48:
        raise ValueError(f"目視レビュー対応が48件ではありません: {len(review_by_asset)}")
    result = []
    for texel in texel_rows:
        review = review_by_asset.get(str(texel["asset"]))
        if review is None:
            raise ValueError(f"目視レビュー対応がありません: {texel['asset']}")
        if review["class"] != texel["class"]:
            raise ValueError(f"classが不一致です: {texel['asset']}")
        result.append({**texel, **review})
    missing = sorted(set(review_by_asset) - {str(row["asset"]) for row in texel_rows})
    if missing:
        raise ValueError(f"テクセル密度がない目視レビューがあります: {missing}")
    return result


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
            raise ValueError(
                f"{class_name}: クラス内アセット数が3ではありません ({len(class_rows)})"
            )
        for metric in TEXEL_METRICS:
            ordered = sorted(
                class_rows, key=lambda row: (-float(row[metric]), str(row["asset"]))
            )
            output: dict[str, Any] = {"class": class_name, "metric": metric}
            minimum = min(float(row[metric]) for row in class_rows)
            for index, row in enumerate(ordered, start=1):
                asset = str(row["asset"])
                ranks[(asset, metric)] = index
                if np.isclose(float(row[metric]), minimum, rtol=1e-12, atol=1e-15):
                    lowest.add((asset, metric))
                slot = ("best", "middle", "lowest")[index - 1]
                output[f"{slot}_asset"] = asset
                output[f"{slot}_value"] = round(float(row[metric]), 6)
            table.append(output)
    return table, ranks, lowest


def build_summaries(
    non_example_rows: list[dict[str, Any]],
    ranks: dict[tuple[str, str], int],
    lowest: set[tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lowest_counts: list[dict[str, Any]] = []
    distributions: list[dict[str, Any]] = []
    for label_field in LABEL_FIELDS:
        for metric in TEXEL_METRICS:
            yes_rows = [row for row in non_example_rows if row[label_field] == "yes"]
            count = sum((str(row["asset"]), metric) in lowest for row in yes_rows)
            n = len(yes_rows)
            lowest_counts.append(
                {
                    "source": "texel_density_20261001",
                    "label": label_field,
                    "metric": metric,
                    "lowest_count": count,
                    "yes_count": n,
                    "fraction": f"{count} / {n}",
                    "chance_expectation": round(n / 3.0, 6),
                }
            )
            for label_value in ("yes", "no"):
                selected = [
                    row for row in non_example_rows if row[label_field] == label_value
                ]
                if not selected:
                    continue
                rank_values = [
                    float(ranks[(str(row["asset"]), metric)]) for row in selected
                ]
                raw_values = [float(row[metric]) for row in selected]
                distributions.append(
                    {
                        "label": label_field,
                        "label_value": label_value,
                        "metric": metric,
                        "measure": "class_rank_1_best_3_lowest",
                        **distribution(rank_values),
                    }
                )
                distributions.append(
                    {
                        "label": label_field,
                        "label_value": label_value,
                        "metric": metric,
                        "measure": "raw_px_per_m",
                        **distribution(raw_values),
                    }
                )
    return lowest_counts, distributions


def previous_lowest_counts(path: Path) -> list[dict[str, Any]]:
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = result.get("lowest_counts")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"既存比較JSONにlowest_countsがありません: {path}")
    return [{"source": "studio_material_20260930", **row} for row in rows]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="テクセル密度と目視レビューをクラス内順位で照合する"
    )
    parser.add_argument("texel_csv", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("key", type=Path)
    parser.add_argument("previous_result", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    texel_path = args.texel_csv.resolve()
    labels_path = args.labels.resolve()
    key_path = args.key.resolve()
    previous_path = args.previous_result.resolve()
    output_dir = args.output_dir.resolve()

    rows = attach_review(
        load_texel_rows(texel_path), load_review_rows(labels_path, key_path)
    )
    rank_table, ranks, lowest = class_rankings(rows)
    non_example_rows = [row for row in rows if row["is_example"] != "yes"]
    lowest_counts, distributions = build_summaries(non_example_rows, ranks, lowest)
    prior_counts = previous_lowest_counts(previous_path)
    combined_counts = prior_counts + lowest_counts

    asset_rows = [
        {
            "asset": row["asset"],
            "class": row["class"],
            "weighted_median_px_per_m": round(float(row["weighted_median_px_per_m"]), 6),
            "weighted_p10_px_per_m": round(float(row["weighted_p10_px_per_m"]), 6),
            "detail_lost": row["detail_lost"],
            "flat_surface": row["flat_surface"],
        }
        for row in non_example_rows
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    asset_path = output_dir / "texel_density_review_asset_table_20261001.csv"
    ranks_path = output_dir / "texel_density_class_ranks_20261001.csv"
    counts_path = output_dir / "texel_density_lowest_counts_20261001.csv"
    distributions_path = output_dir / "texel_density_label_distributions_20261001.csv"
    combined_path = output_dir / "material_metric_lowest_counts_combined_20261001.csv"
    result_path = output_dir / "texel_density_review_result_20261001.json"
    write_csv(asset_path, list(asset_rows[0]), asset_rows)
    write_csv(ranks_path, list(rank_table[0]), rank_table)
    write_csv(counts_path, list(lowest_counts[0]), lowest_counts)
    write_csv(distributions_path, list(distributions[0]), distributions)
    write_csv(combined_path, list(combined_counts[0]), combined_counts)

    result = {
        "texel_csv": str(texel_path),
        "texel_csv_sha256": file_sha256(texel_path),
        "labels": str(labels_path),
        "labels_sha256": file_sha256(labels_path),
        "key": str(key_path),
        "key_sha256": file_sha256(key_path),
        "previous_result": str(previous_path),
        "previous_result_sha256": file_sha256(previous_path),
        "rank_population": "all 48 assets, three variants per class",
        "examples_excluded_from_label_summary": sum(
            row["is_example"] == "yes" for row in rows
        ),
        "assets_in_label_summary": len(non_example_rows),
        "thresholds_or_pass_fail": "none",
        "lowest_counts": lowest_counts,
        "distributions": distributions,
    }
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"集計: {len(non_example_rows)} assets / 練習用除外: "
        f"{result['examples_excluded_from_label_summary']}"
    )
    print(f"texel CSV SHA-256: {result['texel_csv_sha256']}")
    print(f"labels SHA-256: {result['labels_sha256']}")
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
            f"IQR=[{row['q1']}, {row['q3']}] "
            f"range=[{row['minimum']}, {row['maximum']}]"
        )
    print("\n出力:")
    for path in (
        asset_path,
        ranks_path,
        counts_path,
        distributions_path,
        combined_path,
        result_path,
    ):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
