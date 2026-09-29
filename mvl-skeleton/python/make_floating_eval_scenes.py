#!/usr/bin/env python3
"""既存シーンから、浮遊検出率を測るための欠陥注入シーンを作る。"""
import argparse
import copy
import json
from pathlib import Path

import machine_checks as mc


FLOATING_TARGETS = ("chair_01", "backpack_01", "monitor_01", "laptop_01")
GAPS_BY_SEED = (
    (0.05, 0.15, 0.30, 0.50),
    (0.15, 0.30, 0.50, 0.20),
    (0.30, 0.50, 0.20, 0.40),
)


def _move_contact_to(scene, obj, target_y):
    aabb = mc.nominal_aabb(obj)
    contact, _ = mc.contact_y(scene, obj, (aabb[0], aabb[1]))
    obj["position"][1] += float(target_y) - contact


def normalize_vertical_support(scene):
    """公称寸法上で、全物体を宣言された床・支持面へ戻す。"""
    objects = {obj.get("id"): obj for obj in scene.get("objects", [])}
    floor_y = float(scene.get("room", {}).get("floor_y", 0.0))
    completed = set()
    visiting = set()

    def normalize(obj):
        object_id = obj.get("id")
        if object_id in completed:
            return
        if object_id in visiting:
            raise ValueError(f"rests_onが循環している: {object_id}")
        visiting.add(object_id)
        parent_id = obj.get("rests_on")
        if parent_id:
            parent = objects.get(parent_id)
            if parent is None:
                raise ValueError(f"rests_on先が存在しない: {object_id} -> {parent_id}")
            normalize(parent)
            parent_aabb = mc.nominal_aabb(parent)
            target_y, _ = mc.support_y(
                scene, parent, (parent_aabb[0], parent_aabb[1]))
            _move_contact_to(scene, obj, target_y)
        elif obj.get("must_touch_floor", True):
            _move_contact_to(scene, obj, floor_y)
        visiting.remove(object_id)
        completed.add(object_id)

    for item in scene.get("objects", []):
        normalize(item)


def inject_floating_defects(scene, gaps):
    """支持状態を正規化後、4物体へ指定した浮遊量を注入する。"""
    if len(gaps) != len(FLOATING_TARGETS):
        raise ValueError(f"浮遊量は{len(FLOATING_TARGETS)}個必要")
    result = copy.deepcopy(scene)
    normalize_vertical_support(result)
    objects = {obj.get("id"): obj for obj in result.get("objects", [])}
    injected = []

    for object_id, gap in zip(FLOATING_TARGETS, gaps):
        obj = objects.get(object_id)
        if obj is None:
            raise ValueError(f"浮遊評価に必要な物体がない: {object_id}")
        gap = float(gap)
        if gap <= mc.FLOOR_TOL:
            raise ValueError(f"浮遊量が機械検査の許容値以下: {object_id}={gap}")
        obj["position"][1] += gap
        injected.append({
            "object_id": object_id,
            "support": obj.get("rests_on", "floor"),
            "injected_gap_m": gap,
        })

    original_id = result.get("scene_id", "scene")
    result["scene_id"] = f"{original_id}_floating_eval"
    result["evaluation_injection"] = {
        "kind": "floating",
        "expected_positive_count": len(injected),
        "objects": injected,
        "note": "検出率測定専用。通常シーンや本番シーンとして使用しない。",
    }

    violations = mc.check_floating(result, mc.collect_aabbs(result))
    positive_ids = {v.get("object_id") for v in violations
                    if v.get("type") == "floating"}
    expected_ids = set(FLOATING_TARGETS)
    if positive_ids != expected_ids:
        raise RuntimeError(
            f"浮遊正解ラベルの検証失敗: expected={sorted(expected_ids)}, "
            f"actual={sorted(positive_ids)}")
    return result


def build_scene(source_path, output_path, gaps):
    source_path = Path(source_path).resolve()
    scene = json.loads(source_path.read_text(encoding="utf-8"))
    scene["assets_dir"] = str(
        (source_path.parent / scene.get("assets_dir", "assets")).resolve())
    result = inject_floating_defects(scene, gaps)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="3シードへ浮遊違反を各4件注入し、評価専用JSONを作る")
    parser.add_argument("scenes", nargs=3, help="元のscene JSON 3個")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    for index, (scene_path, gaps) in enumerate(zip(args.scenes, GAPS_BY_SEED), 1):
        output = output_dir / f"scene_study_seed{index}_floating_eval.json"
        build_scene(scene_path, output, gaps)
        gap_text = ", ".join(f"{gap:.2f}m" for gap in gaps)
        print(f"seed{index}: {output} / floating=4 / gaps={gap_text}")
    print("合計: floating正解ラベル 12件")


if __name__ == "__main__":
    main()
