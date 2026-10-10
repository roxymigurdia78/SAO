#!/usr/bin/env python3
"""2x2テクスチャ画像をVLMで盲検判定し、人手ラベルと照合する。"""
import argparse
import csv
import hashlib
import json
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PROMPT = (
    SCRIPT_DIR / "prompts" / "texture_repetition_audit_v1_20260930.txt")
DEFAULT_MODEL = "qwen3.5:35b"
PREDICTION_FIELDS = (
    "blind_id", "unnatural_repetition", "confidence", "detail")


def validate_prediction(result):
    """VLM応答を厳格に検証し、保存可能な形へ正規化する。"""
    if not isinstance(result, dict):
        raise ValueError("判定応答がJSONオブジェクトではない")
    verdict = result.get("unnatural_repetition")
    if not isinstance(verdict, bool):
        raise ValueError("unnatural_repetitionは真偽値である必要がある")
    confidence = result.get("confidence")
    if (not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not math.isfinite(float(confidence))
            or not 0.0 <= float(confidence) <= 1.0):
        raise ValueError("confidenceは0.0以上1.0以下の有限な数値である必要がある")
    detail = result.get("detail")
    if not isinstance(detail, str) or not detail.strip():
        raise ValueError("detailは空でない文字列である必要がある")
    return {
        "unnatural_repetition": verdict,
        "confidence": float(confidence),
        "detail": detail.strip(),
    }


def load_predictions(path):
    path = Path(path)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"予測ファイルの最上位は配列である必要があります: {path}")
    normalized = []
    seen = set()
    for item in data:
        if not isinstance(item, dict) or not item.get("blind_id"):
            raise ValueError(f"blind_idのない予測があります: {path}")
        blind_id = str(item["blind_id"])
        if blind_id in seen:
            raise ValueError(f"予測のblind_idが重複しています: {blind_id}")
        seen.add(blind_id)
        normalized.append({"blind_id": blind_id, **validate_prediction(item)})
    return normalized


def save_predictions(path, predictions):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(predictions, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    temporary_path.replace(path)


def load_labels(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    labels = {}
    for row in rows:
        blind_id = row.get("blind_id", "").strip()
        label = row.get("visual_label", "").strip().lower()
        if not blind_id or label not in ("reject", "acceptable"):
            raise ValueError(
                f"人手ラベルが不正です: blind_id={blind_id!r}, label={label!r}")
        if blind_id in labels:
            raise ValueError(f"人手ラベルのblind_idが重複しています: {blind_id}")
        labels[blind_id] = label
    return labels


def evaluate_predictions(predictions, labels):
    """rejectを陽性として混同行列と主要指標を返す。"""
    predicted_by_id = {row["blind_id"]: row for row in predictions}
    if set(predicted_by_id) != set(labels):
        missing = sorted(set(labels) - set(predicted_by_id))
        extra = sorted(set(predicted_by_id) - set(labels))
        raise ValueError(f"予測とラベルのIDが一致しません: missing={missing}, extra={extra}")

    rows = []
    counts = {"tp": 0, "fn": 0, "fp": 0, "tn": 0}
    for blind_id in sorted(labels):
        prediction = predicted_by_id[blind_id]
        truth_positive = labels[blind_id] == "reject"
        predicted_positive = prediction["unnatural_repetition"]
        outcome = (
            "tp" if truth_positive and predicted_positive else
            "fn" if truth_positive else
            "fp" if predicted_positive else "tn")
        counts[outcome] += 1
        rows.append({
            **prediction,
            "visual_label": labels[blind_id],
            "outcome": outcome.upper(),
        })

    def rate(numerator, denominator):
        return numerator / denominator if denominator else None

    tp, fn, fp, tn = (counts[key] for key in ("tp", "fn", "fp", "tn"))
    metrics = {
        "sample_count": len(rows),
        **counts,
        "detection_rate": rate(tp, tp + fn),
        "false_positive_rate": rate(fp, fp + tn),
        "precision": rate(tp, tp + fp),
        "accuracy": rate(tp + tn, len(rows)),
    }
    return rows, metrics


def write_evaluation_csv(path, rows):
    fields = (*PREDICTION_FIELDS, "visual_label", "outcome")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def prompt_sha256(prompt_text):
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


def ensure_run_config(path, prompt_text, model):
    """再開時にモデルやプロンプトの異なる予測が混ざるのを防ぐ。"""
    path = Path(path)
    expected = {
        "evaluation": "texture_unnatural_repetition_vlm_v1",
        "prompt_frozen_date": date(2026, 9, 30).isoformat(),
        "model": model,
        "prompt_sha256": prompt_sha256(prompt_text),
    }
    if path.is_file():
        actual = json.loads(path.read_text(encoding="utf-8"))
        if actual != expected:
            raise ValueError(
                "既存実行とモデルまたはプロンプトが異なります。"
                "別のoutput-dirを指定してください")
        return actual
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(expected, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return expected


def build_manifest(prompt_path, prompt_text, model, samples_dir, labels_path,
                   metrics):
    return {
        "evaluation": "texture_unnatural_repetition_vlm_v1",
        "prompt_frozen_date": date(2026, 9, 30).isoformat(),
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "prompt_path": str(Path(prompt_path).resolve()),
        "prompt_sha256": prompt_sha256(prompt_text),
        "samples_dir": str(Path(samples_dir).resolve()),
        "labels_path": str(Path(labels_path).resolve()),
        "positive_label": "reject",
        "positive_prediction": "unnatural_repetition=true",
        "metrics": metrics,
    }


def print_summary(metrics):
    def percent(value):
        return "N/A" if value is None else f"{value:.1%}"

    print("\n不自然な反復 VLM評価（rejectを陽性）")
    print("                 VLM true  VLM false")
    print(f"  reject          {metrics['tp']:>4}       {metrics['fn']:>4}")
    print(f"  acceptable      {metrics['fp']:>4}       {metrics['tn']:>4}")
    print(f"  検出率={percent(metrics['detection_rate'])} / "
          f"誤検出率={percent(metrics['false_positive_rate'])} / "
          f"適合率={percent(metrics['precision'])} / "
          f"正解率={percent(metrics['accuracy'])}")


def run_predictions(samples_dir, predictions_path, prompt_text, ask):
    """ラベルを参照せず、未判定画像だけを1枚ずつ判定する。"""
    samples = sorted(Path(samples_dir).glob("*.png"))
    if not samples:
        raise FileNotFoundError(f"PNG画像がありません: {samples_dir}")
    predictions = load_predictions(predictions_path)
    completed = {row["blind_id"] for row in predictions}
    sample_ids = {path.stem for path in samples}
    unknown = completed - sample_ids
    if unknown:
        raise ValueError(f"予測にsamples内にないIDがあります: {sorted(unknown)}")

    for index, image_path in enumerate(samples, 1):
        blind_id = image_path.stem
        if blind_id in completed:
            print(f"[{index}/{len(samples)}] {blind_id}: 保存済みのためスキップ")
            continue
        print(f"[{index}/{len(samples)}] {blind_id}: VLM判定")
        result = ask(prompt_text, [image_path], validator=validate_prediction)
        predictions.append({"blind_id": blind_id, **result})
        predictions.sort(key=lambda row: row["blind_id"])
        save_predictions(predictions_path, predictions)
    return predictions


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="2x2テクスチャ20枚のVLM盲検判定と人手ラベル評価")
    parser.add_argument("samples_dir", help="B001.png等を置いたディレクトリ")
    parser.add_argument("labels_csv", help="blind_id,visual_labelを持つ正解CSV")
    parser.add_argument("--output-dir", default="texture_repetition_vlm_eval")
    parser.add_argument("--prompt", default=str(DEFAULT_PROMPT))
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL") or DEFAULT_MODEL)
    parser.add_argument(
        "--evaluate-only", action="store_true",
        help="保存済みpredictions.jsonだけを正解ラベルと照合する")
    args = parser.parse_args(argv)

    samples_dir = Path(args.samples_dir)
    labels_path = Path(args.labels_csv)
    output_dir = Path(args.output_dir)
    prompt_path = Path(args.prompt)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    predictions_path = output_dir / "predictions.json"
    ensure_run_config(output_dir / "run_config.json", prompt_text, args.model)

    if args.evaluate_only:
        predictions = load_predictions(predictions_path)
    else:
        import gpt_scoring
        gpt_scoring.MODEL = args.model
        predictions = run_predictions(
            samples_dir, predictions_path, prompt_text, gpt_scoring._ask)

    # 盲検性のため、正解ラベルは全予測が揃った後に初めて読み込む。
    sample_count = len(list(samples_dir.glob("*.png")))
    if len(predictions) != sample_count:
        raise RuntimeError(
            f"全予測が揃っていないため評価しません: {len(predictions)}/{sample_count}")
    labels = load_labels(labels_path)
    rows, metrics = evaluate_predictions(predictions, labels)
    write_evaluation_csv(output_dir / "evaluation.csv", rows)
    manifest = build_manifest(
        prompt_path, prompt_text, args.model, samples_dir, labels_path, metrics)
    (output_dir / "result.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print_summary(metrics)
    print(f"\n予測: {predictions_path.resolve()}")
    print(f"評価: {(output_dir / 'evaluation.csv').resolve()}")
    print(f"記録: {(output_dir / 'result.json').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
