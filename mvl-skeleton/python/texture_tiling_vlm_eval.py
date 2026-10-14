#!/usr/bin/env python3
"""2x2テクスチャをVLMで継ぎ目・反復の2軸判定し、人手ラベルと照合する。"""
import argparse
import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from texture_reaudit_eval import load_reaudit_labels
from texture_repetition_vlm_eval import evaluate_predictions


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PROMPT = (
    SCRIPT_DIR / "prompts" / "texture_tiling_audit_dev_v2_20260930.txt")
DEFAULT_MODEL = "qwen3.5:35b"
AXES = ("visible_seam", "unnatural_repetition")


def _validate_confidence(value, field):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(float(value))
            or not 0.0 <= float(value) <= 1.0):
        raise ValueError(f"{field}は0.0以上1.0以下の有限な数値である必要がある")
    return float(value)


def validate_prediction(result):
    if not isinstance(result, dict):
        raise ValueError("判定応答がJSONオブジェクトではない")
    normalized = {}
    for axis in AXES:
        verdict = result.get(axis)
        if not isinstance(verdict, bool):
            raise ValueError(f"{axis}は真偽値である必要がある")
        confidence_field = f"{axis}_confidence"
        detail_field = f"{axis}_detail"
        detail = result.get(detail_field)
        if not isinstance(detail, str) or not detail.strip():
            raise ValueError(f"{detail_field}は空でない文字列である必要がある")
        normalized[axis] = verdict
        normalized[confidence_field] = _validate_confidence(
            result.get(confidence_field), confidence_field)
        normalized[detail_field] = detail.strip()
    return normalized


def load_predictions(path):
    path = Path(path)
    if not path.is_file():
        return []
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError("予測JSONの最上位は配列である必要がある")
    rows = []
    seen = set()
    for value in values:
        blind_id = value.get("blind_id") if isinstance(value, dict) else None
        if not blind_id or blind_id in seen:
            raise ValueError(f"blind_idがないか重複しています: {blind_id!r}")
        seen.add(blind_id)
        rows.append({"blind_id": blind_id, **validate_prediction(value)})
    return rows


def save_json_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    temporary.replace(path)


def run_config(prompt_text, model):
    return {
        "evaluation": "texture_tiling_two_axis_v1",
        "stage": "development",
        "model": model,
        "prompt_sha256": hashlib.sha256(
            prompt_text.encode("utf-8")).hexdigest(),
    }


def ensure_run_config(path, expected):
    path = Path(path)
    if path.is_file():
        actual = json.loads(path.read_text(encoding="utf-8"))
        if actual != expected:
            raise ValueError(
                "既存実行とモデルまたはプロンプトが異なります。"
                "別のoutput-dirを指定してください")
        return
    save_json_atomic(path, expected)


def run_predictions(samples_dir, predictions_path, prompt_text, ask):
    samples = sorted(Path(samples_dir).glob("*.png"))
    if not samples:
        raise FileNotFoundError(f"PNG画像がありません: {samples_dir}")
    predictions = load_predictions(predictions_path)
    completed = {row["blind_id"] for row in predictions}
    sample_ids = {path.stem for path in samples}
    if completed - sample_ids:
        raise ValueError(f"samples内にない保存済みIDがあります: {completed - sample_ids}")
    for index, image_path in enumerate(samples, 1):
        blind_id = image_path.stem
        if blind_id in completed:
            print(f"[{index}/{len(samples)}] {blind_id}: 保存済みのためスキップ")
            continue
        print(f"[{index}/{len(samples)}] {blind_id}: 2軸VLM判定")
        result = ask(prompt_text, [image_path], validator=validate_prediction)
        predictions.append({"blind_id": blind_id, **result})
        predictions.sort(key=lambda row: row["blind_id"])
        save_json_atomic(predictions_path, predictions)
    return predictions


def evaluate_axes(predictions, labels):
    details = []
    metrics = {}
    for axis in AXES:
        compatible_predictions = [{
            "blind_id": row["blind_id"],
            "unnatural_repetition": row[axis],
            "confidence": row[f"{axis}_confidence"],
            "detail": row[f"{axis}_detail"],
        } for row in predictions]
        truth = {
            blind_id: "reject" if values[axis] == "yes" else "acceptable"
            for blind_id, values in labels.items()
        }
        rows, metrics[axis] = evaluate_predictions(compatible_predictions, truth)
        for row in rows:
            details.append({
                "axis": axis,
                "blind_id": row["blind_id"],
                "predicted": row["unnatural_repetition"],
                "confidence": row["confidence"],
                "detail": row["detail"],
                "human_label": row["visual_label"],
                "outcome": row["outcome"],
            })
    return details, metrics


def write_evaluation_csv(path, rows):
    fields = ("axis", "blind_id", "predicted", "confidence", "detail",
              "human_label", "outcome")
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def print_metrics(metrics):
    def percent(value):
        return "N/A" if value is None else f"{value:.1%}"
    print("\n2軸VLM評価")
    for axis in AXES:
        row = metrics[axis]
        print(f"[{axis}] TP={row['tp']} FN={row['fn']} "
              f"FP={row['fp']} TN={row['tn']} / "
              f"検出率={percent(row['detection_rate'])} / "
              f"誤検出率={percent(row['false_positive_rate'])} / "
              f"正解率={percent(row['accuracy'])}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="継ぎ目・反復の2軸VLM評価")
    parser.add_argument("samples_dir")
    parser.add_argument("labels_csv")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--prompt", default=str(DEFAULT_PROMPT))
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--evaluate-only", action="store_true")
    args = parser.parse_args(argv)

    samples_dir = Path(args.samples_dir)
    labels_path = Path(args.labels_csv)
    output_dir = Path(args.output_dir)
    prompt_path = Path(args.prompt)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    config = run_config(prompt_text, args.model)
    ensure_run_config(output_dir / "run_config.json", config)
    predictions_path = output_dir / "predictions.json"

    if args.evaluate_only:
        predictions = load_predictions(predictions_path)
    else:
        import gpt_scoring
        gpt_scoring.MODEL = args.model
        predictions = run_predictions(
            samples_dir, predictions_path, prompt_text, gpt_scoring._ask)

    sample_count = len(list(samples_dir.glob("*.png")))
    if len(predictions) != sample_count:
        raise RuntimeError(
            f"全予測が揃っていないため評価しません: {len(predictions)}/{sample_count}")
    labels = load_reaudit_labels(labels_path)
    rows, metrics = evaluate_axes(predictions, labels)
    write_evaluation_csv(output_dir / "evaluation.csv", rows)
    save_json_atomic(output_dir / "result.json", {
        **config,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "development_set_post_hoc_labels",
        "prompt_path": str(prompt_path.resolve()),
        "samples_dir": str(samples_dir.resolve()),
        "labels_path": str(labels_path.resolve()),
        "metrics_by_axis": metrics,
    })
    print_metrics(metrics)
    print(f"\n予測: {predictions_path.resolve()}")
    print(f"評価: {(output_dir / 'evaluation.csv').resolve()}")
    print(f"記録: {(output_dir / 'result.json').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
