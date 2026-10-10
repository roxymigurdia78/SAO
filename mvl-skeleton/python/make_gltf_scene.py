"""GLB を指しているシーンJSONから、変換済みの .gltf セットを指すシーンJSONを作る。

使い方（mvl-skeleton で）:
    python python/make_gltf_scene.py scene/scene_study_seed1.json --gltf-dir assets/gltf/1006 --suffix _4096
    python python/make_gltf_scene.py scene/scene_study_seed1.json scene/scene_study_seed2.json scene/scene_study_seed3.json --gltf-dir assets/gltf/1006 --suffix _4096

やること:
    - assets_dir を --gltf-dir に変える（シーンJSONのフォルダからの相対パス）
    - 各物の asset と asset_variants を "desk_v1.glb" → "desk_v1/desk_v1.gltf" に変える
      （convert_glb_to_gltf.py が物ごとのフォルダに出力するため）
    - scene_id の後ろに --suffix を付ける
    - 元のファイルは変えず、<元の名前><suffix>.json として横に保存する

注意:
    - repair.py の一部（寸法インベントリ、物の追加）は .glb 前提なので、
      ここで作ったシーンでループを回すには repair.py の対応が別に必要。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def to_gltf_name(asset: str) -> str:
    """"desk_v1.glb" → "desk_v1/desk_v1.gltf"。.glb 以外はそのまま返す。"""
    p = Path(asset)
    if p.suffix.lower() != ".glb":
        return asset
    return f"{p.stem}/{p.stem}.gltf"


def convert_scene(scene: dict, gltf_dir: str, suffix: str) -> tuple[dict, list[str]]:
    """シーンの中身を書き換えて、参照している .gltf の一覧と一緒に返す。"""
    scene = json.loads(json.dumps(scene))  # 元の dict を変えないようにコピー
    original_assets_dir = scene.get("assets_dir")
    scene["assets_dir"] = gltf_dir
    scene["scene_id"] = f"{scene.get('scene_id', 'scene')}{suffix}"
    # どこから作ったかを残しておく（SceneBuilder は知らない項目を無視する）
    scene["derived_from"] = {"assets_dir": original_assets_dir, "tool": "make_gltf_scene.py"}

    referenced: list[str] = []
    for obj in scene.get("objects", []):
        if "asset" in obj:
            obj["asset"] = to_gltf_name(obj["asset"])
            referenced.append(obj["asset"])
        if obj.get("asset_variants"):
            obj["asset_variants"] = [to_gltf_name(a) for a in obj["asset_variants"]]
            referenced.extend(obj["asset_variants"])
    return scene, sorted(set(referenced))


def main() -> int:
    parser = argparse.ArgumentParser(description="GLBシーンから.gltfセット用のシーンJSONを作る")
    parser.add_argument("scenes", nargs="+", type=Path, help="元のシーンJSON（複数可）")
    parser.add_argument("--gltf-dir", required=True,
                        help="変換済みセットのフォルダ（シーンJSONのフォルダからの相対パス）例: assets/gltf/1006")
    parser.add_argument("--suffix", required=True, help="出力ファイル名と scene_id に付ける文字 例: _4096")
    parser.add_argument("--overwrite", action="store_true", help="出力先が既にあっても上書きする")
    args = parser.parse_args()

    failed = 0
    for src in args.scenes:
        dst = src.with_name(f"{src.stem}{args.suffix}{src.suffix}")
        if dst.exists() and not args.overwrite:
            print(f"スキップ（既にある。上書きするなら --overwrite）: {dst}")
            continue

        scene = json.loads(src.read_text(encoding="utf-8"))
        new_scene, referenced = convert_scene(scene, args.gltf_dir, args.suffix)

        # 作ったシーンが指すファイルが本当にあるか確かめる。
        # 無いものがあれば保存しない（Unityで「GLBなし」とスキップされるのを先に防ぐ）。
        base = src.parent / args.gltf_dir
        missing = [a for a in referenced if not (base / a).is_file()]
        if missing:
            failed += 1
            print(f"失敗: {src.name} の参照先が {len(missing)} 個見つかりません（{base}）", file=sys.stderr)
            for a in missing[:10]:
                print(f"    {a}", file=sys.stderr)
            continue

        dst.write_text(json.dumps(new_scene, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"作成: {dst}（物 {len(new_scene.get('objects', []))} 個、参照ファイル {len(referenced)} 個すべて確認済み）")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
