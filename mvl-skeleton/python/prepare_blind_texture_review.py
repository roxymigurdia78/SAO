"""番号と指標を伏せた、テクスチャ目視評価セットを作る。

出力する回答用CSVと画像には元ファイル名や測定値を含めない。
対応表は別ファイルに保存し、目視ラベルを確定するまで開かない。
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

from PIL import Image, ImageDraw


def _save_2x2(source: Path, destination: Path, tile_size: int = 512) -> None:
    with Image.open(source) as image:
        tile = image.convert("RGB")
        tile.thumbnail((tile_size, tile_size), Image.Resampling.LANCZOS)
        preview = Image.new("RGB", (tile.width * 2, tile.height * 2))
        for y in (0, tile.height):
            for x in (0, tile.width):
                preview.paste(tile, (x, y))
        destination.parent.mkdir(parents=True, exist_ok=True)
        preview.save(destination)


def _save_contact_sheets(blind_ids: list[str], sample_dir: Path,
                         output_dir: Path, per_sheet: int = 6) -> list[Path]:
    panel_width, image_height, label_height = 520, 500, 40
    columns = 2
    rows = (per_sheet + columns - 1) // columns
    destinations = []

    for page_index, start in enumerate(range(0, len(blind_ids), per_sheet), 1):
        page_ids = blind_ids[start:start + per_sheet]
        sheet = Image.new(
            "RGB", (panel_width * columns, (image_height + label_height) * rows),
            "white")
        draw = ImageDraw.Draw(sheet)

        for index, blind_id in enumerate(page_ids):
            x = (index % columns) * panel_width
            y = (index // columns) * (image_height + label_height)
            with Image.open(sample_dir / f"{blind_id}.png") as image:
                preview = image.convert("RGB")
                preview.thumbnail(
                    (panel_width, image_height), Image.Resampling.LANCZOS)
                image_x = x + (panel_width - preview.width) // 2
                sheet.paste(preview, (image_x, y))
            draw.text((x + 10, y + image_height + 10), blind_id, fill="black")

        destination = output_dir / f"blind_review_{page_index:02d}.png"
        sheet.save(destination)
        destinations.append(destination)

    return destinations


def prepare_blind_review(input_dir: Path, output_dir: Path,
                         pattern: str = "wall_*.png", seed: int | None = None,
                         per_sheet: int = 6) -> dict[str, Path | list[Path] | int]:
    files = sorted(input_dir.glob(pattern))
    if not files:
        raise FileNotFoundError(f"対象画像がありません: {input_dir / pattern}")
    if per_sheet < 1:
        raise ValueError("per_sheet は1以上にしてください")

    shuffled = list(files)
    if seed is None:
        random.SystemRandom().shuffle(shuffled)
    else:
        random.Random(seed).shuffle(shuffled)

    output_dir.mkdir(parents=True, exist_ok=False)
    sample_dir = output_dir / "samples"
    sample_dir.mkdir()

    mapping_rows = []
    answer_rows = []
    blind_ids = []
    for index, source in enumerate(shuffled, 1):
        blind_id = f"B{index:03d}"
        blind_ids.append(blind_id)
        _save_2x2(source, sample_dir / f"{blind_id}.png")
        mapping_rows.append({"blind_id": blind_id, "source_file": source.name})
        answer_rows.append({
            "blind_id": blind_id,
            "visual_label": "",
            "defect_type": "",
            "note": "",
        })

    mapping_csv = output_dir / "mapping_DO_NOT_OPEN.csv"
    with mapping_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(mapping_rows[0]))
        writer.writeheader()
        writer.writerows(mapping_rows)

    answers_csv = output_dir / "visual_labels.csv"
    with answers_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(answer_rows[0]))
        writer.writeheader()
        writer.writerows(answer_rows)

    sheets = _save_contact_sheets(
        blind_ids, sample_dir, output_dir, per_sheet=per_sheet)
    return {
        "count": len(files),
        "answers_csv": answers_csv,
        "mapping_csv": mapping_csv,
        "sample_dir": sample_dir,
        "sheets": sheets,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="元番号と測定値を隠した2x2テクスチャ評価セットを作る")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--pattern", default="wall_*.png")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--per-sheet", type=int, default=6)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = prepare_blind_review(
        args.input_dir.resolve(), args.output_dir.resolve(),
        pattern=args.pattern, seed=args.seed, per_sheet=args.per_sheet)
    print(f"Images : {result['count']}")
    print(f"Labels : {result['answers_csv']}")
    print(f"Samples: {result['sample_dir']}")
    for sheet in result["sheets"]:
        print(f"Review : {sheet}")
    print("目視ラベルを確定するまで mapping_DO_NOT_OPEN.csv は開かないでください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
