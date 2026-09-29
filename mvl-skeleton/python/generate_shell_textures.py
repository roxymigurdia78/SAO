"""シーンJSONの材質の文章から、殻（床・壁・天井）のタイル用テクスチャを生成する。

使い方:
    python generate_shell_textures.py --scene ../scene/scene_study_seed1.json --dry-run
    python generate_shell_textures.py --scene ../scene/scene_study_seed1.json

出力:
    mvl-skeleton/images/shell/<日時>_<scene_id>/
        floor.png, wall.png, ceiling.png, manifest.json

このスクリプトは「生成するだけ」。継ぎ目や影の検査は別スクリプトでやる。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 画像APIの呼び出しと .env の読み込みは既存スクリプトのものをそのまま使う
from generate_material_variants import generate_one, load_env_file, save_manifest

# ---------------------------------------------------------------------------
# プロンプト
#   タイル用テクスチャでよく起きる失敗を、先に言葉で防いでおく。
#   - 遠近感がつく（斜めから撮った写真になる）→ "orthographic, flat"
#   - 影や光のムラが焼き込まれる → "evenly lit, no shadows, no vignetting"
#   - 端がつながらない → "seamless tileable"
#   それでも失敗はするので、検査スクリプトで拾う。
# ---------------------------------------------------------------------------
TEXTURE_TEMPLATE = (
    "Seamless tileable texture of {material}. "
    "Orthographic flat view, perfectly straight on, no perspective. "
    "Evenly lit, no shadows, no highlights, no vignetting, no objects. "
    "Fills the entire frame edge to edge. Photorealistic surface detail. "
    "{surface_instruction}"
)

SURFACE_INSTRUCTIONS = {
    "floor": (
        "Continuous flooring crosses all four image edges naturally. "
        "No border, no frame, no grout lines, and no square tile boundary. "
        "Do not align plank ends or seams with the image border. "
        "The left and right edges must match exactly, and the top and bottom "
        "edges must match exactly."
    ),
    "wall": (
        "A single continuous wall surface with subtle irregular detail only. "
        "No panels, no grid, no border, no corners, and no architectural "
        "features. All opposite edges must match exactly."
    ),
    "ceiling": (
        "A single continuous ceiling surface with very subtle fine detail. "
        "No panels, no grid, no border, no beams, and no fixtures. "
        "All opposite edges must match exactly."
    ),
}

# シーンJSONに ceiling_material が無いときの既定値
DEFAULT_CEILING = "matte white painted ceiling plaster"


def build_prompt(surface: str, material: str) -> str:
    """面ごとの失敗パターンを避ける指示を加えた生成プロンプトを作る。"""
    return TEXTURE_TEMPLATE.format(
        material=material,
        surface_instruction=SURFACE_INSTRUCTIONS[surface],
    )


def load_surfaces(scene_path: Path) -> tuple[str, dict[str, str]]:
    """シーンJSONから scene_id と、面ごとの材質の文章を取り出す。"""
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    room = scene["room"]
    surfaces = {
        "floor": room.get("floor_material"),
        "wall": room.get("wall_material"),
        "ceiling": room.get("ceiling_material") or DEFAULT_CEILING,
    }
    missing = [name for name, text in surfaces.items() if not text]
    if missing:
        raise ValueError(f"シーンJSONに材質の記述がありません: {missing}")
    return scene.get("scene_id", scene_path.stem), surfaces


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="殻のタイル用テクスチャを生成する")
    p.add_argument("--scene", type=Path, required=True, help="シーンJSONのパス")
    p.add_argument("--surfaces", nargs="+", default=["floor", "wall", "ceiling"],
                   choices=["floor", "wall", "ceiling"])
    p.add_argument("--model", default="gpt-image-2")
    p.add_argument("--quality", choices=["low", "medium", "high"], default="low")
    p.add_argument("--size", default="1024x1024")
    p.add_argument("--delay", type=float, default=1.0)
    p.add_argument("--output-root", type=Path,
                   default=Path(__file__).resolve().parents[1] / "images" / "shell")
    p.add_argument("--dry-run", action="store_true", help="APIを呼ばずに計画だけ表示")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    scene_id, surfaces = load_surfaces(args.scene)

    run_dir = args.output_root.resolve() / f"{datetime.now():%Y%m%d_%H%M%S}_{scene_id}"
    plan = [
        {
            "surface": name,
            "material_text": surfaces[name],
            "prompt": build_prompt(name, surfaces[name]),
            "output": str(run_dir / f"{name}.png"),
        }
        for name in args.surfaces
    ]

    print(f"Scene : {args.scene} ({scene_id})")
    print(f"Output: {run_dir}")
    for item in plan:
        print(f"  {item['surface']:8s} <- \"{item['material_text']}\"")
        print(f"           prompt: {item['prompt']}")
    if args.dry_run:
        print("Dry run: APIは呼んでいません。")
        return 0

    load_env_file(Path(__file__).with_name(".env"))
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY が未設定です", file=sys.stderr)
        return 2
    from openai import OpenAI

    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scene": str(args.scene),
        "scene_id": scene_id,
        "model": args.model,
        "quality": args.quality,
        "size": args.size,
        "template": TEXTURE_TEMPLATE,
        "surface_instructions": SURFACE_INSTRUCTIONS,
        "textures": plan,
    }
    manifest_path = run_dir / "manifest.json"
    save_manifest(manifest_path, manifest)

    client = OpenAI()
    failures = 0
    for i, item in enumerate(plan, start=1):
        print(f"[{i}/{len(plan)}] {item['surface']} を生成中 ...")
        try:
            generate_one(client, args.model, args.quality, args.size,
                         item["prompt"], Path(item["output"]))
            item["status"] = "success"
        except Exception as exc:  # 1枚失敗しても残りは続ける
            failures += 1
            item["status"] = "failed"
            item["error"] = str(exc)
            print(f"    失敗: {exc}", file=sys.stderr)
        save_manifest(manifest_path, manifest)
        if i < len(plan) and args.delay:
            time.sleep(args.delay)

    print(f"完了: {len(plan) - failures}/{len(plan)} 枚 -> {run_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
