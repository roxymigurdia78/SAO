#!/usr/bin/env python3
"""機械検査を正解として詳細VLMの浮遊・貫通検出を集計する。"""
import argparse
import csv
import json
from pathlib import Path


COMPARABLE_KINDS = ("floating", "penetration")
COUNT_ONLY_KINDS = ("scale", "orientation", "functional_relation")


def _machine_positive_ids(violations, kind):
    ids = set()
    for violation in violations or []:
        if violation.get("type") != kind:
            continue
        if kind == "penetration":
            ids.update(value for value in violation.get("object_ids", [])
                       if value)
        elif violation.get("object_id"):
            ids.add(violation["object_id"])
    return ids


def _vlm_positive_ids(audits, kind):
    ids = set()
    for audit in audits or []:
        object_id = audit.get("object_id")
        if not object_id:
            continue
        if any(finding.get("kind") == kind
               for finding in audit.get("findings", [])):
            ids.add(object_id)
    return ids


def _vlm_finding_count(audits, kind):
    return sum(
        finding.get("kind") == kind
        for audit in audits or []
        for finding in audit.get("findings", []))


def _rate(numerator, denominator):
    return numerator / denominator if denominator else None


def evaluate_records(violations, audits, scope="input"):
    """1反復を物体×項目で評価し、CSV向け行を返す。"""
    universe = {
        audit.get("object_id") for audit in audits or []
        if audit.get("object_id")
    }
    rows = []
    for kind in COMPARABLE_KINDS:
        truth = _machine_positive_ids(violations, kind) & universe
        predicted = _vlm_positive_ids(audits, kind) & universe
        tp = len(truth & predicted)
        fn = len(truth - predicted)
        fp = len(predicted - truth)
        tn = len(universe - truth - predicted)
        rows.append({
            "section": "confusion",
            "scope": str(scope),
            "item": kind,
            "audited_objects": len(universe),
            "tp": tp,
            "fn": fn,
            "fp": fp,
            "tn": tn,
            "detection_rate": _rate(tp, tp + fn),
            "false_positive_rate": _rate(fp, fp + tn),
            "machine_positive_objects": len(truth),
            "vlm_positive_objects": len(predicted),
            "vlm_findings": _vlm_finding_count(audits, kind),
        })

    for kind in COUNT_ONLY_KINDS:
        machine_ids = _machine_positive_ids(violations, kind) & universe
        vlm_ids = _vlm_positive_ids(audits, kind) & universe
        rows.append({
            "section": "count_only",
            "scope": str(scope),
            "item": kind,
            "audited_objects": len(universe),
            "tp": None,
            "fn": None,
            "fp": None,
            "tn": None,
            "detection_rate": None,
            "false_positive_rate": None,
            "machine_positive_objects": (
                len(machine_ids) if kind == "scale" else None),
            "vlm_positive_objects": len(vlm_ids),
            "vlm_findings": _vlm_finding_count(audits, kind),
        })
    return rows


def load_iteration(iteration_dir):
    iteration_dir = Path(iteration_dir)
    violations_path = iteration_dir / "violations.json"
    audits_path = iteration_dir / "detail_audit.json"
    if not violations_path.is_file():
        raise FileNotFoundError(f"violations.json がありません: {iteration_dir}")
    if not audits_path.is_file():
        raise FileNotFoundError(f"detail_audit.json がありません: {iteration_dir}")
    violations = json.loads(violations_path.read_text(encoding="utf-8"))
    audits = json.loads(audits_path.read_text(encoding="utf-8"))
    if not isinstance(violations, list) or not isinstance(audits, list):
        raise ValueError(f"JSONの最上位は配列である必要があります: {iteration_dir}")
    return evaluate_records(violations, audits, scope=iteration_dir)


def aggregate_rows(rows, scope="TOTAL"):
    """複数反復を試行単位で加算する。物体IDが同じでも別試行として数える。"""
    result = []
    for kind in COMPARABLE_KINDS:
        selected = [row for row in rows
                    if row["section"] == "confusion" and row["item"] == kind]
        totals = {key: sum(row[key] for row in selected)
                  for key in ("audited_objects", "tp", "fn", "fp", "tn",
                              "machine_positive_objects", "vlm_positive_objects",
                              "vlm_findings")}
        result.append({
            "section": "confusion", "scope": scope, "item": kind,
            **totals,
            "detection_rate": _rate(totals["tp"], totals["tp"] + totals["fn"]),
            "false_positive_rate": _rate(
                totals["fp"], totals["fp"] + totals["tn"]),
        })
    comparable = list(result)
    combined = {key: sum(row[key] for row in comparable)
                for key in ("audited_objects", "tp", "fn", "fp", "tn",
                            "machine_positive_objects", "vlm_positive_objects",
                            "vlm_findings")}
    result.append({
        "section": "confusion", "scope": scope,
        "item": "floating+penetration", **combined,
        "detection_rate": _rate(
            combined["tp"], combined["tp"] + combined["fn"]),
        "false_positive_rate": _rate(
            combined["fp"], combined["fp"] + combined["tn"]),
    })
    for kind in COUNT_ONLY_KINDS:
        selected = [row for row in rows
                    if row["section"] == "count_only" and row["item"] == kind]
        result.append({
            "section": "count_only", "scope": scope, "item": kind,
            "audited_objects": sum(row["audited_objects"] for row in selected),
            "tp": None, "fn": None, "fp": None, "tn": None,
            "detection_rate": None, "false_positive_rate": None,
            "machine_positive_objects": (
                sum((row["machine_positive_objects"] or 0) for row in selected)
                if kind == "scale" else None),
            "vlm_positive_objects": sum(row["vlm_positive_objects"] for row in selected),
            "vlm_findings": sum(row["vlm_findings"] for row in selected),
        })
    return result


def write_csv(path, rows):
    fields = [
        "section", "scope", "item", "audited_objects",
        "tp", "fn", "fp", "tn", "detection_rate", "false_positive_rate",
        "machine_positive_objects", "vlm_positive_objects", "vlm_findings",
    ]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _percent(value):
    return "N/A" if value is None else f"{value:.1%}"


def print_summary(rows):
    totals = [row for row in rows if row["scope"] == "TOTAL"]
    print("浮遊・貫通（機械検査と詳細VLMで問いが一致）")
    for row in totals:
        if row["section"] != "confusion":
            continue
        print(f"\n[{row['item']}] 物体×項目")
        print("                 VLM指摘あり  VLM指摘なし")
        print(f"  正解あり       {row['tp']:>6}       {row['fn']:>6}")
        print(f"  正解なし       {row['fp']:>6}       {row['tn']:>6}")
        print(f"  検出率={_percent(row['detection_rate'])} / "
              f"誤検出率={_percent(row['false_positive_rate'])}")

    print("\n別枠集計")
    for row in totals:
        if row["section"] != "count_only":
            continue
        if row["item"] == "scale":
            print("  scale: 機械検査は仕様寸法、VLMは見た目の妥当性で問いが異なる。"
                  f" 機械指摘物体={row['machine_positive_objects']}, "
                  f"VLM指摘物体={row['vlm_positive_objects']}, "
                  f"VLM指摘件数={row['vlm_findings']}")
        else:
            print(f"  {row['item']}: 正解ラベルなし / "
                  f"VLM指摘物体={row['vlm_positive_objects']}, "
                  f"VLM指摘件数={row['vlm_findings']}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="詳細VLMと機械検査を物体×項目で突き合わせる")
    parser.add_argument(
        "iteration_dirs", nargs="+",
        help="runs/<run>/iter_XX ディレクトリ（複数指定可）")
    parser.add_argument(
        "--csv", default="detail_vlm_eval.csv",
        help="集計CSVの出力先（既定: detail_vlm_eval.csv）")
    args = parser.parse_args(argv)

    detail_rows = []
    for directory in args.iteration_dirs:
        detail_rows.extend(load_iteration(directory))
    rows = detail_rows + aggregate_rows(detail_rows)
    write_csv(args.csv, rows)
    print_summary(rows)
    print(f"\nCSV: {Path(args.csv).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
