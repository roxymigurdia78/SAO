#!/usr/bin/env python3
"""既存の詳細画像を再利用し、改訂前後の詳細VLM検出率を比較する。"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import gpt_scoring
from detail_vlm_eval import evaluate_records


FIELDS = [
    "condition", "item", "tp", "fn", "fp", "tn",
    "detection_rate", "false_positive_rate", "vlm_positive_objects",
    "vlm_findings",
]


def _load(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"必要なファイルがありません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _metric_rows(violations, audits, condition):
    rows = evaluate_records(violations, audits, scope=condition)
    wanted = {"floating", "penetration", "orientation"}
    return [
        {"condition": condition, **{key: row[key] for key in FIELDS[1:]}}
        for row in rows
        if row["section"] == "confusion" and row["item"] in wanted
    ]


def _percent(value):
    return "N/A" if value is None else f"{value:.1%}"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("iteration_dir", help="再利用する runs/.../iter_00")
    parser.add_argument(
        "--prompt",
        default=str(gpt_scoring.PROMPT_DIR / "detail_audit_prompt_v3.txt"),
        help="評価する候補プロンプト（既定: 保存済みv3）")
    parser.add_argument("--candidate-label", default="revised_v3")
    parser.add_argument("--output", help="改訂版audit JSONの出力先")
    parser.add_argument("--csv", help="比較CSVの出力先")
    args = parser.parse_args(argv)

    iteration_dir = Path(args.iteration_dir).resolve()
    capture_dir = iteration_dir / "capture"
    scene = _load(iteration_dir / "scene.json")
    report = _load(capture_dir / "report.json")
    violations = _load(iteration_dir / "violations.json")
    baseline = _load(iteration_dir / "detail_audit.json")
    detail_captures = report.get("detail_captures", []) or []
    if not detail_captures:
        raise ValueError("report.json にdetail_capturesがありません")

    revised = gpt_scoring.audit_scene_details(
        detail_captures, capture_dir, scene, prompt_path=args.prompt)
    output_path = Path(args.output) if args.output else (
        iteration_dir / "detail_audit_prompt_v3.json")
    csv_path = Path(args.csv) if args.csv else (
        iteration_dir / "prompt_revision_comparison_v3.csv")
    output_path.write_text(
        json.dumps(revised, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = _metric_rows(violations, baseline, "baseline_v1")
    rows += _metric_rows(violations, revised, args.candidate_label)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    prompt_path = Path(args.prompt).resolve()
    prompt_hash = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    metadata = {
        "iteration_dir": str(iteration_dir),
        "baseline": str(iteration_dir / "detail_audit.json"),
        "revised": str(output_path.resolve()),
        "comparison_csv": str(csv_path.resolve()),
        "prompt_sha256": prompt_hash,
        "audited_objects": len(revised),
        "invalid_after_retries": sum(
            audit.get("error") == "vlm_invalid_after_retries"
            for audit in revised),
    }
    (iteration_dir / "prompt_revision_metadata_v3.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"detail prompt revision: baseline_v1 vs {args.candidate_label}")
    for row in rows:
        print(
            f"  {row['condition']:>11} {row['item']}: "
            f"tp={row['tp']} fn={row['fn']} fp={row['fp']} tn={row['tn']} "
            f"detection={_percent(row['detection_rate'])} "
            f"false_positive={_percent(row['false_positive_rate'])}"
        )
    print(f"\ninvalid_after_retries={metadata['invalid_after_retries']}")
    print(f"audit JSON: {output_path.resolve()}")
    print(f"comparison CSV: {csv_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
