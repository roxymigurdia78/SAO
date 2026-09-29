#!/usr/bin/env python3
"""既存シーンから、向き検出率を測るための欠陥注入シーンを作る。"""
import argparse
import copy
import json
from pathlib import Path

import machine_checks as mc


FACING_TARGETS = {
    "desk_01": "chair_01",
    "chair_01": "desk_01",
    "monitor_01": "chair_01",
    "laptop_01": "chair_01",
}


def inject_orientation_defects(scene, front_offsets, error_deg):
    """4物体へfaces制約と既知の角度誤差を注入したコピーを返す。"""
    result = copy.deepcopy(scene)
    objects = {obj.get("id"): obj for obj in result.get("objects", [])}
    injected = []

    for object_id, target_id in FACING_TARGETS.items():
        obj = objects.get(object_id)
        target = objects.get(target_id)
        if obj is None or target is None:
            raise ValueError(f"向き評価に必要な物体がない: {object_id} -> {target_id}")
        offset = mc.front_offset_deg(result, obj, front_offsets)
        if offset is None:
            raise ValueError(f"front_offset_degが未確認: {obj.get('asset')}")
        desired = mc.desired_facing_yaw(obj, target)
        if desired is None:
            raise ValueError(f"対象と同じ位置のため向きを定義できない: {object_id}")

        obj["faces"] = target_id
        obj["faces_tolerance_deg"] = mc.DEFAULT_FACE_TOLERANCE_DEG
        obj["rotation_y_deg"] = (desired - offset + float(error_deg)) % 360.0
        injected.append({
            "object_id": object_id,
            "target_id": target_id,
            "injected_error_deg": float(error_deg),
        })

    original_id = result.get("scene_id", "scene")
    result["scene_id"] = f"{original_id}_orientation_eval"
    result["evaluation_injection"] = {
        "kind": "orientation",
        "expected_positive_count": len(injected),
        "objects": injected,
        "note": "検出率測定専用。通常シーンや本番シーンとして使用しない。",
    }
    return result


def build_scene(source_path, output_path, error_deg):
    source_path = Path(source_path).resolve()
    scene = json.loads(source_path.read_text(encoding="utf-8"))
    assets_dir = (source_path.parent / scene.get("assets_dir", "assets")).resolve()
    scene["assets_dir"] = str(assets_dir)
    offsets = mc.load_asset_front_offsets(str(assets_dir))
    result = inject_orientation_defects(scene, offsets, error_deg)

    violations = mc.check_semantic_constraints(result, offsets)
    orientation = [v for v in violations if v.get("type") == "orientation"]
    unverified = [v for v in violations if v.get("type") == "orientation_unverified"]
    if len(orientation) != len(FACING_TARGETS) or unverified:
        raise RuntimeError(
            f"向き正解ラベルの検証失敗: orientation={len(orientation)}, "
            f"unverified={len(unverified)}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="3シードへ向き違反を各4件注入し、評価専用JSONを作る")
    parser.add_argument("scenes", nargs=3, help="元のscene JSON 3個")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--errors", nargs=3, type=float, default=(90.0, 135.0, 180.0),
        metavar=("SEED1_DEG", "SEED2_DEG", "SEED3_DEG"),
        help="各シードへ注入する角度誤差（既定: 90 135 180）")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    for index, (scene_path, error) in enumerate(zip(args.scenes, args.errors), 1):
        output = output_dir / f"scene_study_seed{index}_orientation_eval.json"
        build_scene(scene_path, output, error)
        print(f"seed{index}: {output} / orientation=4 / error={error:g}deg")
    print("合計: orientation正解ラベル 12件")


if __name__ == "__main__":
    main()
