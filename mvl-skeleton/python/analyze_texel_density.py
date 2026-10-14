"""GLBのbaseColorテクセル密度を、target_dimensions適用後の実寸で集計する。

GLB、シーン階層、UV、材質の読み取りはtrimeshへ任せ、本プロジェクトでは
実寸スケール、三角形密度、面積加重P50/P10、CSV/JSON出力だけを実装する。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

try:
    import trimesh
except ImportError as error:
    raise SystemExit(
        "trimesh が必要です。先に python -m pip install -r requirements.txt "
        "を実行してください。"
    ) from error


QUEST2_REFERENCE_PX_PER_M = 1100.0
EPSILON = 1e-15
ASSET_PATTERN = re.compile(r"^(?P<class_name>.+)_v(?P<variant>[123])\.glb$", re.I)
OUTPUT_FIELDS = (
    "asset", "class", "variant",
    "target_width_m", "target_height_m", "target_depth_m",
    "scale_x", "scale_y", "scale_z",
    "source_triangle_count", "analyzed_triangle_count", "degenerate_triangle_count",
    "surface_area_m2",
    "basecolor_mapped_area_fraction", "zero_uv_area_fraction",
    "weighted_median_px_per_m", "weighted_p10_px_per_m",
    "mapped_min_px_per_m", "mapped_max_px_per_m",
    "quest2_reference_px_per_m",
)


@dataclass
class PrimitiveInstance:
    positions: np.ndarray
    triangles: np.ndarray
    uvs: np.ndarray | None
    texture_size: tuple[int, int] | None


def _as_scene(loaded: Any) -> Any:
    if isinstance(loaded, trimesh.Scene):
        return loaded
    if isinstance(loaded, trimesh.Trimesh):
        return trimesh.Scene(loaded)
    raise ValueError(f"未対応のtrimesh読み込み結果です: {type(loaded).__name__}")


def _texture_size(material: Any) -> tuple[int, int] | None:
    """PBRMaterialまたはSimpleMaterialのbaseColor画像サイズを返す。"""
    if material is None:
        return None
    image = getattr(material, "baseColorTexture", None)
    if image is None:
        image = getattr(material, "image", None)
    if image is None:
        return None
    size = getattr(image, "size", None)
    if size is not None and len(size) == 2:
        return int(size[0]), int(size[1])
    shape = getattr(image, "shape", None)
    if shape is not None and len(shape) >= 2:
        return int(shape[1]), int(shape[0])
    return None


def collect_primitives(path: Path) -> list[PrimitiveInstance]:
    """trimeshでGLBを読み、ノード変換適用済みの三角形メッシュを返す。"""
    scene = _as_scene(trimesh.load(path, force="scene", process=False))
    result: list[PrimitiveInstance] = []
    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        mesh = scene.geometry[geometry_name]
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
            continue
        positions = trimesh.transform_points(
            np.asarray(mesh.vertices, dtype=np.float64),
            np.asarray(transform, dtype=np.float64),
        )
        triangles = np.asarray(mesh.faces, dtype=np.int64)
        visual = getattr(mesh, "visual", None)
        candidate = getattr(visual, "uv", None)
        uvs = None
        if candidate is not None:
            candidate = np.asarray(candidate, dtype=np.float64)
            if candidate.ndim == 2 and candidate.shape == (len(positions), 2):
                uvs = candidate
        result.append(
            PrimitiveInstance(
                positions=positions,
                triangles=triangles,
                uvs=uvs,
                texture_size=_texture_size(getattr(visual, "material", None)),
            )
        )
    if not result:
        raise ValueError(f"{path}: 三角形プリミティブがありません")
    return result


def triangle_areas_3d(triangles: np.ndarray) -> np.ndarray:
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    return np.linalg.norm(cross, axis=1) * 0.5


def triangle_areas_uv(triangles: np.ndarray) -> np.ndarray:
    first = triangles[:, 1] - triangles[:, 0]
    second = triangles[:, 2] - triangles[:, 0]
    return np.abs(first[:, 0] * second[:, 1] - first[:, 1] * second[:, 0]) * 0.5


def texels_per_meter(
    triangles_3d: np.ndarray,
    triangles_uv: np.ndarray,
    texture_width: int,
    texture_height: int,
) -> np.ndarray:
    area_3d = triangle_areas_3d(triangles_3d)
    area_uv = triangle_areas_uv(triangles_uv)
    output = np.zeros_like(area_3d)
    valid = area_3d > EPSILON
    output[valid] = np.sqrt(
        area_uv[valid] * float(texture_width * texture_height) / area_3d[valid]
    )
    return output


def weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantileは0から1の範囲で指定してください")
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not np.any(valid):
        raise ValueError("面積重み付き分位点を計算できる値がありません")
    values, weights = values[valid], weights[valid]
    order = np.argsort(values, kind="stable")
    values, weights = values[order], weights[order]
    threshold = quantile * np.sum(weights)
    index = int(np.searchsorted(np.cumsum(weights), threshold, side="left"))
    return float(values[min(index, len(values) - 1)])


def target_map(scene_path: Path) -> dict[str, dict[str, Any]]:
    scene = json.loads(scene_path.read_text(encoding="utf-8-sig"))
    result: dict[str, dict[str, Any]] = {}
    for obj in scene.get("objects", []):
        dimensions = obj.get("target_dimensions")
        if not dimensions:
            continue
        for asset in obj.get("asset_variants") or [obj.get("asset")]:
            if not asset:
                continue
            if asset in result:
                raise ValueError(f"シーンJSON内でアセットが重複しています: {asset}")
            result[asset] = {
                "class": obj.get("class", ""),
                "width": float(dimensions["width"]),
                "height": float(dimensions["height"]),
                "depth": float(dimensions["depth"]),
            }
    return result


def analyze_asset(path: Path, target: dict[str, Any]) -> dict[str, Any]:
    primitives = collect_primitives(path)
    extents = np.ptp(np.vstack([p.positions for p in primitives]), axis=0)
    if np.any(extents <= 1e-12):
        raise ValueError(f"{path}: AABB寸法が0です: {extents.tolist()}")
    scale = np.asarray(
        [target["width"], target["height"], target["depth"]], dtype=np.float64
    ) / extents

    density_parts: list[np.ndarray] = []
    area_parts: list[np.ndarray] = []
    mapped_parts: list[np.ndarray] = []
    zero_uv_parts: list[np.ndarray] = []
    source_triangle_count = 0
    analyzed_triangle_count = 0
    for primitive in primitives:
        triangles_3d = (primitive.positions * scale)[primitive.triangles]
        source_triangle_count += len(triangles_3d)
        areas = triangle_areas_3d(triangles_3d)
        valid = areas > EPSILON
        if not np.any(valid):
            continue
        areas = areas[valid]
        analyzed_triangle_count += int(np.count_nonzero(valid))
        density = np.zeros(len(areas), dtype=np.float64)
        mapped = np.zeros(len(areas), dtype=bool)
        zero_uv = np.zeros(len(areas), dtype=bool)
        if primitive.uvs is not None and primitive.texture_size is not None:
            triangles_uv = primitive.uvs[primitive.triangles][valid]
            uv_areas = triangle_areas_uv(triangles_uv)
            width, height = primitive.texture_size
            density = texels_per_meter(triangles_3d[valid], triangles_uv, width, height)
            mapped[:] = True
            zero_uv = uv_areas <= EPSILON
        density_parts.append(density)
        area_parts.append(areas)
        mapped_parts.append(mapped)
        zero_uv_parts.append(zero_uv)

    if not area_parts:
        raise ValueError(f"{path}: 有効な3D三角形がありません")
    densities = np.concatenate(density_parts)
    areas = np.concatenate(area_parts)
    mapped = np.concatenate(mapped_parts)
    zero_uv = np.concatenate(zero_uv_parts)
    if not np.any(mapped):
        raise ValueError(f"{path}: baseColorテクスチャとUVを持つ三角形がありません")
    total_area = float(np.sum(areas))
    mapped_density = densities[mapped]
    match = ASSET_PATTERN.match(path.name)
    return {
        "asset": path.stem,
        "class": target["class"],
        "variant": int(match.group("variant")) if match else "",
        "target_width_m": target["width"],
        "target_height_m": target["height"],
        "target_depth_m": target["depth"],
        "scale_x": round(float(scale[0]), 10),
        "scale_y": round(float(scale[1]), 10),
        "scale_z": round(float(scale[2]), 10),
        "source_triangle_count": source_triangle_count,
        "analyzed_triangle_count": analyzed_triangle_count,
        "degenerate_triangle_count": source_triangle_count - analyzed_triangle_count,
        "surface_area_m2": round(total_area, 10),
        "basecolor_mapped_area_fraction": round(float(np.sum(areas[mapped])) / total_area, 10),
        "zero_uv_area_fraction": round(float(np.sum(areas[zero_uv])) / total_area, 10),
        "weighted_median_px_per_m": round(
            weighted_quantile(densities[mapped], areas[mapped], 0.5), 6
        ),
        "weighted_p10_px_per_m": round(
            weighted_quantile(densities[mapped], areas[mapped], 0.1), 6
        ),
        "mapped_min_px_per_m": round(float(np.min(mapped_density)), 6),
        "mapped_max_px_per_m": round(float(np.max(mapped_density)), 6),
        "quest2_reference_px_per_m": QUEST2_REFERENCE_PX_PER_M,
    }


def ordinary_distribution(values: Iterable[float]) -> dict[str, float]:
    array = np.asarray(list(values), dtype=np.float64)
    return {
        "minimum": round(float(np.min(array)), 6),
        "p10": round(float(np.quantile(array, 0.10)), 6),
        "q1": round(float(np.quantile(array, 0.25)), 6),
        "median": round(float(np.median(array)), 6),
        "q3": round(float(np.quantile(array, 0.75)), 6),
        "p90": round(float(np.quantile(array, 0.90)), 6),
        "maximum": round(float(np.max(array)), 6),
    }


def read_khronos_reference(path: Path) -> dict[str, Any]:
    """公式Auditorの結果を検算記録として読み込む。

    Auditor 1.0.xのJSONに保存されるpixelsPerMeter.maximum.valueは、実際には
    max(UV面積/3D面積)である。公式コンソール表示はこれに最大テクスチャの
    width*heightを掛けるためpx²/m²となる。本研究のpx/mへ比較用変換する場合は
    その平方根を取る。ただしGLBのネイティブ寸法かつ極値なので、本集計の
    target_dimensions適用後P50/P10とは直接比較しない。
    """
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    try:
        raw_max = float(report["uvs"]["pixelsPerMeter"]["maximum"]["value"])
        texture_width = float(report["textures"]["width"]["maximum"]["value"])
        texture_height = float(report["textures"]["height"]["maximum"]["value"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Khronos参照JSONの形式が不正です: {path}") from error
    area_density = raw_max * texture_width * texture_height
    dimensions = report.get("product", {}).get("overallDimensions", {})
    return {
        "path": str(path.resolve()),
        "auditor_version": report.get("version"),
        "scope": "native GLB dimensions, maximum triangle, largest texture",
        "raw_max_uv_area_per_m2": raw_max,
        "largest_texture_width": int(texture_width),
        "largest_texture_height": int(texture_height),
        "auditor_console_area_density_px2_per_m2": area_density,
        "sqrt_conversion_px_per_m": float(np.sqrt(area_density)),
        "native_dimensions": {
            axis: dimensions.get(axis, {}).get("value")
            for axis in ("length", "width", "height")
        },
        "comparison_note": (
            "Reference only: Khronos 1.0.x reports an extreme UV-area ratio times "
            "texture pixel area, while this study uses target-scaled, surface-area-"
            "weighted P50/P10 of the square-root metric."
        ),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="target_dimensions適用後のGLB baseColorテクセル密度を集計する"
    )
    parser.add_argument("assets_dir", type=Path, help="48個のGLBがあるフォルダ")
    parser.add_argument("scene_json", type=Path, help="target_dimensionsを含むシーンJSON")
    parser.add_argument(
        "--asset",
        help="任意: 動作確認として指定したGLB名だけを解析（例: desk_v1.glb）",
    )
    parser.add_argument("--output", type=Path, required=True, help="アセット別CSV")
    parser.add_argument("--summary", type=Path, required=True, help="分布と計算条件のJSON")
    parser.add_argument(
        "--khronos-reference",
        type=Path,
        help="任意: 公式glTF Asset AuditorのJSONを検算記録としてsummaryへ含める",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    assets_dir, scene_json = args.assets_dir.resolve(), args.scene_json.resolve()
    output, summary_path = args.output.resolve(), args.summary.resolve()
    targets = target_map(scene_json)
    glbs = sorted(assets_dir.glob("*.glb"), key=lambda p: p.name.lower())
    if args.asset:
        selected = assets_dir / args.asset
        if not selected.is_file():
            raise ValueError(f"指定GLBがありません: {selected}")
        glbs = [selected]
        if selected.name not in targets:
            raise ValueError(f"target_dimensionsがありません: {selected.name}")
    else:
        if len(glbs) != 48:
            raise ValueError(f"GLBが48個ではありません: {len(glbs)} ({assets_dir})")
        missing = [p.name for p in glbs if p.name not in targets]
        extra = sorted(set(targets) - {p.name for p in glbs})
        if missing or extra:
            raise ValueError(
                f"GLBとtarget_dimensionsの対応が不完全です: "
                f"missing={missing}, extra={extra}"
            )

    rows = []
    for index, path in enumerate(glbs, 1):
        print(f"[{index}/{len(glbs)}] {path.name}")
        rows.append(analyze_asset(path, targets[path.name]))
    write_csv(output, rows)

    summary = {
        "assets_dir": str(assets_dir),
        "scene_json": str(scene_json),
        "asset_count": len(rows),
        "glb_reader": f"trimesh {trimesh.__version__}",
        "texture_source": "material.pbrMetallicRoughness.baseColorTexture",
        "untextured_surface_policy": "excluded from P50/P10; coverage reported separately",
        "scale_method": "per-axis target_dimensions / transformed GLB AABB",
        "triangle_metric": "sqrt(UV area * texture width * texture height / scaled 3D area)",
        "asset_aggregation": "scaled 3D area-weighted P50 and P10",
        "degenerate_triangle_policy": "zero 3D-area triangles excluded and counted",
        "validation_fields": "mapped triangle min/max for Khronos glTF Asset Auditor comparison",
        "quest2_reference_px_per_m": QUEST2_REFERENCE_PX_PER_M,
        "weighted_median_px_per_m_distribution": ordinary_distribution(
            row["weighted_median_px_per_m"] for row in rows
        ),
        "weighted_p10_px_per_m_distribution": ordinary_distribution(
            row["weighted_p10_px_per_m"] for row in rows
        ),
    }
    if args.khronos_reference is not None:
        summary["khronos_reference"] = read_khronos_reference(
            args.khronos_reference.resolve()
        )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{len(rows)}アセットの分布（px/m）")
    for field in ("weighted_median_px_per_m_distribution", "weighted_p10_px_per_m_distribution"):
        values = summary[field]
        print(
            f"{field}: min={values['minimum']} p10={values['p10']} "
            f"q1={values['q1']} median={values['median']} q3={values['q3']} "
            f"p90={values['p90']} max={values['maximum']}"
        )
    print(f"Quest 2参考値: 約{QUEST2_REFERENCE_PX_PER_M:.0f} px/m")
    print(f"CSV : {output}")
    print(f"JSON: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
