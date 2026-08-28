#!/usr/bin/env python3
"""GLBの正面方向を推定し、assets_inventory.jsonへ記録する。

Unityでは rotation_y_deg=0 のとき +Z を正面とする。方向性のあるクラスは
上部メッシュの重心偏りから前後軸を推定し、0/90/180/270度へ量子化する。
前後の符号を形状だけで決められないクラスは未確定として残し、JSONの
手動上書きを優先する。方向という概念がないクラスは0度(not_applicable)。
"""
import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import contact_offset


# polarity=+1: 上部重心が寄る側を正面、-1: その反対を正面。
# 椅子/ノートPC/本棚は背面側に上部の厚みが寄り、モニターはスタンド・
# 背面機構との相対位置から画面側へ上部中心が寄る、というクラス別根拠。
ASYMMETRY_RULES = {
    "chair": -1,
    "laptop": -1,
    "bookshelf": -1,
    "monitor": 1,
}

# 意味的な「正面」を定義しないクラス。値は互換用の0度だが、orientation
# 制約へ使うための推定値ではないことをmethodに明記する。
NON_DIRECTIONAL_CLASSES = {
    "books", "floor_lamp", "lamp", "mug", "pen_holder", "plant",
    "rug", "trash_bin",
}

UPPER_FRACTION = 0.65
MIN_NORMALIZED_ASYMMETRY = 0.04
CARDINALS = ((0.0, (0.0, 1.0)), (90.0, (1.0, 0.0)),
             (180.0, (0.0, -1.0)), (270.0, (-1.0, 0.0)))


def _load_overrides(path):
    if path is None or not Path(path).is_file():
        return {"assets": {}, "classes": {}}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "assets": data.get("assets", {}),
        "classes": data.get("classes", {}),
    }


def _override_value(entry):
    if isinstance(entry, (int, float)) and not isinstance(entry, bool):
        return float(entry), "manual override"
    if isinstance(entry, dict):
        return float(entry["front_offset_deg"]), entry.get("note", "manual override")
    raise ValueError(f"手動上書きの形式が不正: {entry!r}")


def _cardinal_angle(x, z):
    length = math.hypot(x, z)
    if length < 1e-12:
        return None
    x, z = x / length, z / length
    return min(CARDINALS, key=lambda item: -(x * item[1][0] + z * item[1][1]))[0]


def estimate_asset(path, asset_class, overrides=None):
    """1アセットの推定結果を返す。未確定時はfront_offset_deg=None。"""
    overrides = overrides or {"assets": {}, "classes": {}}
    exact = overrides.get("assets", {}).get(Path(path).name)
    class_override = overrides.get("classes", {}).get(asset_class)
    if exact is not None or class_override is not None:
        value, note = _override_value(exact if exact is not None else class_override)
        return {
            "front_offset_deg": value % 360.0,
            "front_offset_method": "manual_override",
            "front_offset_confidence": "manual",
            "front_offset_note": note,
        }

    if asset_class in NON_DIRECTIONAL_CLASSES:
        return {
            "front_offset_deg": 0.0,
            "front_offset_method": "not_applicable",
            "front_offset_confidence": "not_applicable",
            "front_offset_note": "このクラスでは意味的な正面を定義しない",
        }

    polarity = ASYMMETRY_RULES.get(asset_class)
    if polarity is None:
        return {
            "front_offset_deg": None,
            "front_offset_method": "unresolved",
            "front_offset_confidence": "unresolved",
            "front_offset_note": "形状だけでは前後の符号を説明可能に決められないため手動確認が必要",
        }

    vertices, _ = contact_offset.load_mesh(path)
    lo = vertices.min(axis=0)
    hi = vertices.max(axis=0)
    span = np.maximum(hi - lo, 1e-12)
    upper = vertices[vertices[:, 1] >= lo[1] + UPPER_FRACTION * span[1]]
    if len(upper) == 0:
        return {
            "front_offset_deg": None,
            "front_offset_method": "unresolved",
            "front_offset_confidence": "unresolved",
            "front_offset_note": "上部メッシュ点が得られなかった",
        }
    normalized = (upper.mean(axis=0) - (lo + hi) / 2.0) / span
    horizontal = np.array([normalized[0], normalized[2]])
    axis = int(np.argmax(np.abs(horizontal)))
    strength = float(abs(horizontal[axis]))
    if strength < MIN_NORMALIZED_ASYMMETRY:
        return {
            "front_offset_deg": None,
            "front_offset_method": "unresolved",
            "front_offset_confidence": "unresolved",
            "front_offset_note": (f"上部重心の水平偏り{strength:.3f}が閾値"
                                  f"{MIN_NORMALIZED_ASYMMETRY:.3f}未満"),
        }
    front = horizontal * polarity
    angle = _cardinal_angle(float(front[0]), float(front[1]))
    return {
        "front_offset_deg": angle,
        "front_offset_method": "upper_mesh_asymmetry",
        "front_offset_confidence": round(strength, 4),
        "front_offset_note": (f"上位{(1-UPPER_FRACTION)*100:.0f}%の頂点重心偏り"
                              f" x={normalized[0]:+.3f}, z={normalized[2]:+.3f}; "
                              f"class polarity={polarity:+d}"),
    }


def update_inventory(assets_dir, inventory_path=None, overrides_path=None,
                     report_path=None):
    assets_dir = Path(assets_dir)
    inventory_path = Path(inventory_path or assets_dir / "assets_inventory.json")
    default_overrides = assets_dir.parent.parent / "front_offsets_overrides.json"
    overrides_path = Path(overrides_path or default_overrides)
    report_path = Path(report_path or assets_dir / "front_offsets_report.json")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    overrides = _load_overrides(overrides_path)
    unresolved = []
    results = []
    method_counts = {}
    for asset in inventory.get("assets", []):
        name = asset.get("file") or f"{asset['asset_id']}.glb"
        result = estimate_asset(assets_dir / name, asset.get("class"), overrides)
        asset.update(result)
        results.append({"file": name, "class": asset.get("class"), **result})
        method = result["front_offset_method"]
        method_counts[method] = method_counts.get(method, 0) + 1
        if result["front_offset_deg"] is None:
            unresolved.append(name)
    inventory["front_offsets_updated_at"] = datetime.now(
        timezone.utc).astimezone().isoformat(timespec="seconds")
    inventory["front_offsets_method"] = (
        "upper_mesh_asymmetry with per-asset/class manual overrides; "
        "Unity +Z is 0deg")
    inventory_path.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "generated_at": inventory["front_offsets_updated_at"],
        "count": len(results),
        "resolved_count": len(results) - len(unresolved),
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
        "method_counts": method_counts,
        "overrides_file": str(overrides_path),
        "results": results,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser(description="GLB正面方向の推定とinventory更新")
    ap.add_argument("--assets-dir", required=True)
    ap.add_argument("--inventory")
    ap.add_argument("--overrides")
    ap.add_argument("--report")
    args = ap.parse_args()
    report = update_inventory(args.assets_dir, args.inventory, args.overrides,
                              args.report)
    print(f"正面方向: {report['resolved_count']}/{report['count']}件を記録")
    if report["unresolved"]:
        print("手動確認が必要:")
        for name in report["unresolved"]:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
