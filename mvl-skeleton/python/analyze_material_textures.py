"""Report roughness and metallic channel statistics for embedded GLB textures."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import struct
from pathlib import Path

import numpy as np
from PIL import Image


GLB_HEADER = struct.Struct("<4sII")
CHUNK_HEADER = struct.Struct("<II")
GLB_MAGIC = b"glTF"
GLB_VERSION = 2
JSON_CHUNK_TYPE = 0x4E4F534A
BIN_CHUNK_TYPE = 0x004E4942
ASSET_NAME = re.compile(r"^(?P<asset_class>.+)_v(?P<variant>\d+)$")


def parse_glb(path: Path) -> tuple[dict, bytes]:
    """Return the JSON document and BIN payload from a GLB 2.0 file."""
    data = path.read_bytes()
    if len(data) < GLB_HEADER.size:
        raise ValueError(f"{path}: file is too short to be a GLB")

    magic, version, declared_length = GLB_HEADER.unpack_from(data)
    if magic != GLB_MAGIC or version != GLB_VERSION:
        raise ValueError(f"{path}: expected GLB 2.0")
    if declared_length != len(data):
        raise ValueError(
            f"{path}: declared length {declared_length} differs from {len(data)}"
        )

    chunks: dict[int, bytes] = {}
    offset = GLB_HEADER.size
    while offset < len(data):
        if offset + CHUNK_HEADER.size > len(data):
            raise ValueError(f"{path}: truncated chunk header")
        chunk_length, chunk_type = CHUNK_HEADER.unpack_from(data, offset)
        offset += CHUNK_HEADER.size
        chunk_end = offset + chunk_length
        if chunk_end > len(data):
            raise ValueError(f"{path}: truncated chunk payload")
        chunks[chunk_type] = data[offset:chunk_end]
        offset = chunk_end

    if JSON_CHUNK_TYPE not in chunks or BIN_CHUNK_TYPE not in chunks:
        raise ValueError(f"{path}: expected one JSON chunk and one BIN chunk")

    document = json.loads(chunks[JSON_CHUNK_TYPE].decode("utf-8"))
    return document, chunks[BIN_CHUNK_TYPE]


def metallic_roughness_image(document: dict, binary: bytes, path: Path) -> Image.Image:
    """Load the sole embedded image referenced as metallicRoughnessTexture."""
    texture_indices = {
        pbr["metallicRoughnessTexture"]["index"]
        for material in document.get("materials", [])
        if "metallicRoughnessTexture"
        in (pbr := material.get("pbrMetallicRoughness", {}))
    }
    if len(texture_indices) != 1:
        raise ValueError(
            f"{path}: expected one metallicRoughness texture, found {len(texture_indices)}"
        )

    texture_index = texture_indices.pop()
    image_index = document["textures"][texture_index]["source"]
    image_spec = document["images"][image_index]
    if "bufferView" not in image_spec:
        raise ValueError(f"{path}: metallicRoughness image is not embedded in a bufferView")

    view = document["bufferViews"][image_spec["bufferView"]]
    if view.get("buffer", 0) != 0:
        raise ValueError(f"{path}: metallicRoughness image uses an unsupported buffer")
    start = view.get("byteOffset", 0)
    end = start + view["byteLength"]
    if start < 0 or end > len(binary):
        raise ValueError(f"{path}: metallicRoughness bufferView is out of bounds")

    with Image.open(io.BytesIO(binary[start:end])) as image:
        return image.convert("RGB")


def channel_stats(path: Path) -> dict[str, str | int | float]:
    match = ASSET_NAME.fullmatch(path.stem)
    if not match:
        raise ValueError(f"{path}: expected a name such as desk_v1.glb")

    document, binary = parse_glb(path)
    image = metallic_roughness_image(document, binary, path)
    pixels = np.asarray(image, dtype=np.uint8)
    roughness = pixels[:, :, 1]
    metallic = pixels[:, :, 2]

    return {
        "class": match.group("asset_class"),
        "variant": int(match.group("variant")),
        "file": path.name,
        "width": image.width,
        "height": image.height,
        "g_min": int(roughness.min()),
        "g_max": int(roughness.max()),
        "g_mean": round(float(roughness.mean()), 6),
        "g_stddev": round(float(roughness.std(ddof=0)), 6),
        "g_p01": int(np.percentile(roughness, 1, method="nearest")),
        "g_median": int(np.percentile(roughness, 50, method="nearest")),
        "g_p99": int(np.percentile(roughness, 99, method="nearest")),
        "g_zero_count": int(np.count_nonzero(roughness == 0)),
        "g_255_count": int(np.count_nonzero(roughness == 255)),
        "b_mean": round(float(metallic.mean()), 6),
        "b_max": int(metallic.max()),
    }


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    default_input = project_root / "scene" / "assets" / "0824"
    parser = argparse.ArgumentParser(
        description="Create a CSV of roughness (G) and metallic (B) statistics for GLBs."
    )
    parser.add_argument("--input-dir", type=Path, default=default_input)
    parser.add_argument(
        "--output",
        type=Path,
        default=default_input / "material_texture_stats.csv",
    )
    parser.add_argument("--expected-count", type=int, default=48)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    files = sorted(args.input_dir.resolve().glob("*.glb"))
    if len(files) != args.expected_count:
        raise ValueError(
            f"expected {args.expected_count} GLBs in {args.input_dir}, found {len(files)}"
        )

    rows = [channel_stats(path) for path in files]
    rows.sort(key=lambda row: (str(row["class"]), int(row["variant"])))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"GLBs: {len(rows)}")
    print(f"Classes: {len({row['class'] for row in rows})}")
    print(f"CSV: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
