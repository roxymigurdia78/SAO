"""テクセル密度介入実験のbaseColor画像と撮影manifestを準備する。

prepare:
  GLBからbaseColorを抽出し、Lanczos 4倍とReal-ESRGAN入力を作る。
import-realesrgan:
  外部で生成したReal-ESRGAN 4倍画像を検証し、Unity Assetsへコピーする。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from analyze_material_textures import parse_glb


ASSETS = (
    "laptop_v2.glb",
    "monitor_v2.glb",
    "rug_v1.glb",
    "desk_v1.glb",
    "cabinet_v1.glb",
    "mug_v3.glb",
)
EXPERIMENT_ID = "texel_intervention_20261001"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def embedded_image(document: dict[str, Any], binary: bytes, image_index: int) -> bytes:
    spec = document["images"][image_index]
    if "bufferView" not in spec:
        raise ValueError("外部URIの画像はこの実験では未対応です")
    view = document["bufferViews"][spec["bufferView"]]
    if int(view.get("buffer", 0)) != 0:
        raise ValueError("buffer 0以外の埋め込み画像は未対応です")
    start = int(view.get("byteOffset", 0))
    end = start + int(view["byteLength"])
    if start < 0 or end > len(binary):
        raise ValueError("画像bufferViewがBIN範囲外です")
    return binary[start:end]


def basecolor_image(path: Path) -> tuple[Image.Image, bytes]:
    document, binary = parse_glb(path)
    texture_indices = {
        int(pbr["baseColorTexture"]["index"])
        for material in document.get("materials", [])
        if "baseColorTexture" in (pbr := material.get("pbrMetallicRoughness", {}))
    }
    if len(texture_indices) != 1:
        raise ValueError(
            f"{path}: baseColor textureが1個ではありません: {len(texture_indices)}"
        )
    texture = document["textures"][texture_indices.pop()]
    source = texture.get("source")
    basisu = texture.get("extensions", {}).get("KHR_texture_basisu")
    if basisu is not None:
        source = basisu.get("source")
    if source is None:
        raise ValueError(f"{path}: baseColor texture sourceがありません")
    raw = embedded_image(document, binary, int(source))
    with Image.open(io.BytesIO(raw)) as image:
        mode = "RGBA" if "A" in image.getbands() else "RGB"
        return image.convert(mode), raw


def unity_asset_path(path: Path) -> str:
    resolved = path.resolve()
    assets_root = next(
        (candidate for candidate in (resolved.parent, *resolved.parents)
         if candidate.name == "Assets"),
        None,
    )
    if assets_root is None:
        raise ValueError(f"UnityのAssets配下ではありません: {resolved}")
    return "Assets/" + resolved.relative_to(assets_root).as_posix()


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", compress_level=6)


def prepare(args: argparse.Namespace) -> int:
    assets_dir = args.assets_dir.resolve()
    unity_dir = args.unity_assets_dir.resolve()
    staging_dir = args.staging_dir.resolve()
    manifest_path = args.manifest.resolve()
    input_dir = staging_dir / "realesrgan_input"
    output_dir = staging_dir / "realesrgan_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    overrides: list[dict[str, str]] = []
    for asset in ASSETS:
        glb = assets_dir / asset
        if not glb.is_file():
            raise FileNotFoundError(f"GLBがありません: {glb}")
        image, embedded = basecolor_image(glb)
        original_size = image.size
        four_x_size = (original_size[0] * 4, original_size[1] * 4)
        lanczos = image.resize(four_x_size, Image.Resampling.LANCZOS)
        stem = glb.stem

        input_path = input_dir / f"{stem}.png"
        lanczos_path = unity_dir / stem / "basecolor_lanczos4x.png"
        real_path = unity_dir / stem / "basecolor_realesrgan4x.png"
        save_png(image, input_path)
        save_png(lanczos, lanczos_path)

        overrides.extend(
            [
                {"asset": asset, "label": "original"},
                {
                    "asset": asset,
                    "label": "lanczos4x",
                    "base_color_texture": unity_asset_path(lanczos_path),
                },
                {
                    "asset": asset,
                    "label": "realesrgan4x",
                    "base_color_texture": unity_asset_path(real_path),
                },
            ]
        )
        records.append(
            {
                "asset": asset,
                "role": "high_density_control" if asset == "mug_v3.glb" else "intervention",
                "original_size": list(original_size),
                "four_x_size": list(four_x_size),
                "embedded_image_sha256": sha256_bytes(embedded),
                "realesrgan_input": str(input_path),
                "realesrgan_input_sha256": sha256_file(input_path),
                "lanczos4x": str(lanczos_path),
                "lanczos4x_sha256": sha256_file(lanczos_path),
                "expected_realesrgan_output": str(output_dir / f"{stem}.png"),
                "unity_realesrgan4x": str(real_path),
            }
        )

    manifest = {
        "assets_dir": str(assets_dir),
        "assets": list(ASSETS),
        "capture": {
            "width": 1024,
            "height": 1024,
            "margin": 1.15,
            "elevation_deg": 25.0,
        },
        "material_overrides": overrides,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = {
        "experiment_id": EXPERIMENT_ID,
        "conditions": ["original", "lanczos4x", "realesrgan4x"],
        "controlled_change": "baseColor texture only",
        "unchanged": [
            "metallicRoughness texture",
            "material scalar properties",
            "mesh and UV",
            "frozen AssetStudioCapture camera and lighting",
        ],
        "realesrgan_model": None,
        "realesrgan_scale": 4,
        "assets": records,
    }
    report_path = staging_dir / "preparation_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Assets: {len(records)}")
    print(f"Real-ESRGAN input: {input_dir}")
    print(f"Real-ESRGAN output: {output_dir}")
    print(f"Unity Lanczos textures: {unity_dir}")
    print(f"Manifest: {manifest_path}")
    print(f"Report: {report_path}")
    return 0


def import_realesrgan(args: argparse.Namespace) -> int:
    output_dir = args.output_dir.resolve()
    unity_dir = args.unity_assets_dir.resolve()
    staging_dir = args.staging_dir.resolve()
    report_path = staging_dir / "preparation_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    records = {Path(row["asset"]).stem: row for row in report["assets"]}
    imported = []
    for stem, record in records.items():
        source = output_dir / f"{stem}.png"
        if not source.is_file():
            raise FileNotFoundError(f"Real-ESRGAN出力がありません: {source}")
        with Image.open(source) as image:
            actual = list(image.size)
        expected = list(record["four_x_size"])
        if actual != expected:
            raise ValueError(
                f"{source}: サイズが4倍ではありません: actual={actual}, expected={expected}"
            )
        destination = unity_dir / stem / "basecolor_realesrgan4x.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        record["realesrgan4x_sha256"] = sha256_file(destination)
        record["realesrgan4x_size"] = actual
        imported.append(destination)
    report["realesrgan_model"] = args.model
    report["realesrgan_import_complete"] = True
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Imported: {len(imported)}")
    for path in imported:
        print(path)
    print(f"Report updated: {report_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--assets-dir", type=Path, required=True)
    prepare_parser.add_argument("--unity-assets-dir", type=Path, required=True)
    prepare_parser.add_argument("--staging-dir", type=Path, required=True)
    prepare_parser.add_argument("--manifest", type=Path, required=True)
    prepare_parser.set_defaults(function=prepare)

    import_parser = subparsers.add_parser("import-realesrgan")
    import_parser.add_argument("--output-dir", type=Path, required=True)
    import_parser.add_argument("--unity-assets-dir", type=Path, required=True)
    import_parser.add_argument("--staging-dir", type=Path, required=True)
    import_parser.add_argument("--model", required=True)
    import_parser.set_defaults(function=import_realesrgan)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return int(args.function(args))


if __name__ == "__main__":
    raise SystemExit(main())
