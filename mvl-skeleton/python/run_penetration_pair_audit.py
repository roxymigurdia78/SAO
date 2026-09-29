#!/usr/bin/env python3
"""既存反復のAABB貫通候補を、VLMでペア単位に再確認する。"""
import argparse
import json
from pathlib import Path

import gpt_scoring


def audit_iteration(iteration_dir):
    iteration_dir = Path(iteration_dir)
    capture_dir = iteration_dir / "capture"
    scene_path = iteration_dir / "scene.json"
    violations_path = iteration_dir / "violations.json"
    report_path = capture_dir / "report.json"
    for path in (scene_path, violations_path, report_path):
        if not path.is_file():
            raise FileNotFoundError(f"必要な入力がありません: {path}")

    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    violations = json.loads(violations_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    audits = gpt_scoring.audit_penetration_pairs(
        violations, report.get("detail_captures", []), capture_dir, scene)
    output_path = iteration_dir / "penetration_pair_audit.json"
    output_path.write_text(
        json.dumps(audits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path, audits


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="既存反復の貫通候補をVLMでペア単位に再確認する")
    parser.add_argument("iteration_dirs", nargs="+", help="iter_XX ディレクトリ")
    args = parser.parse_args(argv)
    for directory in args.iteration_dirs:
        output_path, audits = audit_iteration(directory)
        counts = {verdict: sum(audit.get("verdict") == verdict for audit in audits)
                  for verdict in ("penetrating", "not_penetrating", "uncertain")}
        print(f"{output_path}: {len(audits)}ペア / "
              f"貫通 {counts['penetrating']} / "
              f"非貫通 {counts['not_penetrating']} / "
              f"不確実 {counts['uncertain']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
