#!/usr/bin/env python3
"""固定参照パネルとの比較で、2x2テクスチャの全体的不自然さを評価する。"""
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
    SCRIPT_DIR / "prompts" /
    "texture_tiling_comparative_dev_v1_20260930.txt")
DEFAULT_MODEL = "qwen3.5:35b"


def validate_prediction(result):
    if not isinstance(result, dict):
        raise ValueError("判定応答がJSONオブジェクトではない")
    verdict = result.get("unnatural_tiling")
    if not isinstance(verdict, bool):
        raise ValueError("unnatural_tilingは真偽値である必要がある")
    confidence = result.get("confidence")
    if (not isinstance(confidence, (int, float)) or isinstance(confidence, bool)
            or not math.isfinite(float(confidence))
            or not 0.0 <= float(confidence) <= 1.0):
        raise ValueError("confidenceが不正です")
    closer_to = result.get("closer_to")
    if closer_to not in ("acceptable", "unacceptable"):
        raise ValueError("closer_toが不正です")
    if verdict != (closer_to == "unacceptable"):
        raise ValueError("unnatural_tilingとcloser_toが矛盾しています")
    detail = result.get("detail")
    if not isinstance(detail, str) or not detail.strip():
        raise ValueError("detailは空でない文字列である必要がある")
    return {
        "unnatural_tiling": verdict,
        "confidence": float(confidence),
        "closer_to": closer_to,
        "detail": detail.strip(),
    }


def load_predictions(path):
    path = Path(path)
    if not path.is_file():
        return []
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError("予測JSONの最上位は配列である必要がある")
    rows, seen = [], set()
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


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_reference_ids(reference_path):
    metadata_path = Path(reference_path).with_suffix(".json")
    if not metadata_path.is_file():
        raise FileNotFoundError(f"参照パネルのメタデータがありません: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    reference_ids = set(metadata.get("acceptable_reference_ids", []))
    reference_ids.update(metadata.get("unacceptable_reference_ids", []))
    if not reference_ids:
        raise ValueError("参照パネルのIDがメタデータにありません")
    return reference_ids


def run_predictions(samples_dir, reference_path, predictions_path,
                    prompt_text, ask, excluded_ids=()):
    samples = [path for path in sorted(Path(samples_dir).glob("*.png"))
               if path.stem not in set(excluded_ids)]
    if not samples:
        raise FileNotFoundError(f"PNG画像がありません: {samples_dir}")
    predictions = load_predictions(predictions_path)
    completed = {row["blind_id"] for row in predictions}
    for index, candidate in enumerate(samples, 1):
        blind_id = candidate.stem
        if blind_id in completed:
            print(f"[{index}/{len(samples)}] {blind_id}: 保存済みのためスキップ")
            continue
        print(f"[{index}/{len(samples)}] {blind_id}: 参照比較VLM判定")
        result = ask(
            prompt_text, [Path(reference_path), candidate],
            validator=validate_prediction)
        predictions.append({"blind_id": blind_id, **result})
        predictions.sort(key=lambda row: row["blind_id"])
        save_json_atomic(predictions_path, predictions)
    return predictions


def write_evaluation(path, rows):
    fields = ("blind_id", "unnatural_tiling", "confidence", "closer_to",
              "detail", "human_label", "outcome")
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description="固定参照による比較VLM評価")
    parser.add_argument("samples_dir")
    parser.add_argument("labels_csv")
    parser.add_argument("reference_png")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--prompt", default=str(DEFAULT_PROMPT))
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--evaluate-only", action="store_true")
    args = parser.parse_args(argv)

    samples_dir = Path(args.samples_dir)
    labels_path = Path(args.labels_csv)
    reference_path = Path(args.reference_png)
    output_dir = Path(args.output_dir)
    prompt_path = Path(args.prompt)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    reference_ids = load_reference_ids(reference_path)
    config = {
        "evaluation": "texture_tiling_comparative_v1",
        "stage": "development",
        "model": args.model,
        "prompt_sha256": hashlib.sha256(
            prompt_text.encode("utf-8")).hexdigest(),
        "reference_sha256": sha256_file(reference_path),
        "reference_ids_excluded_from_development_metrics": sorted(reference_ids),
    }
    config_path = output_dir / "run_config.json"
    if config_path.is_file():
        if json.loads(config_path.read_text(encoding="utf-8")) != config:
            raise ValueError("既存実行とモデル、プロンプト、参照画像のいずれかが異なります")
    else:
        save_json_atomic(config_path, config)

    predictions_path = output_dir / "predictions.json"
    if args.evaluate_only:
        predictions = load_predictions(predictions_path)
    else:
        import gpt_scoring
        gpt_scoring.MODEL = args.model
        predictions = run_predictions(
            samples_dir, reference_path, predictions_path,
            prompt_text, gpt_scoring._ask, excluded_ids=reference_ids)
    candidate_ids = {
        path.stem for path in samples_dir.glob("*.png")
        if path.stem not in reference_ids
    }
    sample_count = len(candidate_ids)
    if len(predictions) != sample_count:
        raise RuntimeError(
            f"全予測が揃っていないため評価しません: {len(predictions)}/{sample_count}")

    labels = load_reaudit_labels(labels_path)
    truth = {
        blind_id: "reject" if values["quality_gate"] == "yes" else "acceptable"
        for blind_id, values in labels.items() if blind_id in candidate_ids
    }
    compatible_predictions = [{
        "blind_id": row["blind_id"],
        "unnatural_repetition": row["unnatural_tiling"],
        "confidence": row["confidence"],
        "detail": row["detail"],
    } for row in predictions]
    rows, metrics = evaluate_predictions(compatible_predictions, truth)
    by_id = {row["blind_id"]: row for row in predictions}
    output_rows = [{
        **by_id[row["blind_id"]],
        "human_label": row["visual_label"],
        "outcome": row["outcome"],
    } for row in rows]
    write_evaluation(output_dir / "evaluation.csv", output_rows)
    save_json_atomic(output_dir / "result.json", {
        **config,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "development_set_with_fixed_references",
        "reference_path": str(reference_path.resolve()),
        "metrics": metrics,
    })
    percent = lambda value: "N/A" if value is None else f"{value:.1%}"
    print("\n固定参照による全体的不自然さ評価")
    print(f"TP={metrics['tp']} FN={metrics['fn']} "
          f"FP={metrics['fp']} TN={metrics['tn']}")
    print(f"検出率={percent(metrics['detection_rate'])} / "
          f"誤検出率={percent(metrics['false_positive_rate'])} / "
          f"正解率={percent(metrics['accuracy'])}")
    print(f"\n予測: {predictions_path.resolve()}")
    print(f"評価: {(output_dir / 'evaluation.csv').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
