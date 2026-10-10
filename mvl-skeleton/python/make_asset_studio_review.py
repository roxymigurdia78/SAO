"""AssetStudioCapture画像からブラインド目視レビューシートを作る。"""

from __future__ import annotations

import argparse
import csv
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ASSET_PATTERN = re.compile(r"^(?P<class_name>.+)_v(?P<version>[123])$")
AZIMUTHS = (0, 45, 90, 135, 180, 225, 270, 315)
ROWS = ("A", "B", "C")


def load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def discover_assets(input_dir: Path) -> dict[str, dict[int, Path]]:
    classes: dict[str, dict[int, Path]] = {}
    for directory in sorted(input_dir.iterdir(), key=lambda path: path.name.lower()):
        if not directory.is_dir() or "__" in directory.name:
            continue
        match = ASSET_PATTERN.match(directory.name)
        if match is None:
            continue
        images = [directory / f"azimuth_{azimuth:03d}.png" for azimuth in AZIMUTHS]
        missing = [path.name for path in images if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f"8方向画像が揃っていません: {directory} missing={missing}"
            )
        class_name = match.group("class_name")
        version = int(match.group("version"))
        classes.setdefault(class_name, {})[version] = directory

    if not classes:
        raise FileNotFoundError(f"v1/v2/v3の撮影フォルダがありません: {input_dir}")
    incomplete = {
        class_name: sorted(set((1, 2, 3)) - set(versions))
        for class_name, versions in classes.items()
        if set(versions) != {1, 2, 3}
    }
    if incomplete:
        raise ValueError(f"v1/v2/v3が揃っていないクラスがあります: {incomplete}")
    return classes


def make_sheet(
    class_name: str,
    row_mapping: list[tuple[str, int, Path]],
    output_path: Path,
    cell_size: int,
) -> None:
    label_width = max(64, cell_size // 4)
    sheet = Image.new(
        "RGB", (label_width + cell_size * len(AZIMUTHS), cell_size * len(ROWS)),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    font = load_font(max(28, cell_size // 5))

    for row_index, (row_label, _version, directory) in enumerate(row_mapping):
        y = row_index * cell_size
        label_box = draw.textbbox((0, 0), row_label, font=font)
        label_x = (label_width - (label_box[2] - label_box[0])) // 2
        label_y = y + (cell_size - (label_box[3] - label_box[1])) // 2
        draw.text((label_x, label_y), row_label, fill="black", font=font)

        for column, azimuth in enumerate(AZIMUTHS):
            with Image.open(directory / f"azimuth_{azimuth:03d}.png") as source:
                image = source.convert("RGB").resize(
                    (cell_size, cell_size), Image.Resampling.LANCZOS
                )
            x = label_width + column * cell_size
            sheet.paste(image, (x, y))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def write_key(
    path: Path, mappings: list[dict[str, str | int]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=("class", "row", "asset", "version")
        )
        writer.writeheader()
        writer.writerows(mappings)


def write_template(path: Path, classes: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("class", "row", "flat(yes/no)", "blurry_azimuths", "memo"))
        for class_name in classes:
            for row in ROWS:
                writer.writerow((class_name, row, "", "", ""))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="v1/v2/v3の8方向画像を3行×8列のブラインドレビューシートにする"
    )
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260930)
    parser.add_argument("--cell-size", type=int, default=256)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    classes = discover_assets(input_dir)
    if len(classes) != 16:
        raise ValueError(f"16クラスではありません: {len(classes)}")
    if args.cell_size < 64:
        raise ValueError("cell-sizeは64以上にしてください。")

    randomizer = random.Random(args.seed)
    mappings: list[dict[str, str | int]] = []
    for class_name, versions in sorted(classes.items()):
        shuffled_versions = [1, 2, 3]
        randomizer.shuffle(shuffled_versions)
        row_mapping = [
            (row, version, versions[version])
            for row, version in zip(ROWS, shuffled_versions, strict=True)
        ]
        make_sheet(
            class_name,
            row_mapping,
            args.output_dir.resolve() / f"{class_name}.png",
            args.cell_size,
        )
        for row, version, _directory in row_mapping:
            mappings.append(
                {
                    "class": class_name,
                    "row": row,
                    "asset": f"{class_name}_v{version}",
                    "version": version,
                }
            )

    write_key(args.key.resolve(), mappings)
    write_template(args.template.resolve(), sorted(classes))
    print(f"Sheets  : {len(classes)}")
    print(f"Key     : {args.key.resolve()}")
    print(f"Template: {args.template.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
