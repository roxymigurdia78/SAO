#!/usr/bin/env python3
"""比較VLM用に、開発セットの許容・不採用アンカーを固定パネル化する。"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_ACCEPTABLE = ("B002", "B009")
DEFAULT_UNACCEPTABLE = ("B013", "B020")


def _font(size):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def build_panel(samples_dir, acceptable_ids=DEFAULT_ACCEPTABLE,
                unacceptable_ids=DEFAULT_UNACCEPTABLE, tile_size=448):
    groups = (
        ("ACCEPTABLE REFERENCES", acceptable_ids, (225, 245, 230)),
        ("UNNATURAL REFERENCES", unacceptable_ids, (255, 230, 225)),
    )
    margin, gap, header = 16, 16, 30
    columns = max(len(ids) for _, ids, _ in groups)
    width = margin * 2 + tile_size * columns + gap * (columns - 1)
    height = margin * 3 + (header + tile_size) * len(groups)
    panel = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(panel)
    title_font, id_font = _font(22), _font(18)
    y = margin
    for title, blind_ids, fill in groups:
        draw.rectangle((0, y - 4, width, y + header - 2), fill=fill)
        draw.text((margin, y), title, fill="black", font=title_font)
        y += header
        for column, blind_id in enumerate(blind_ids):
            path = Path(samples_dir) / f"{blind_id}.png"
            if not path.is_file():
                raise FileNotFoundError(f"参照画像がありません: {path}")
            with Image.open(path) as source:
                tile = source.convert("RGB").resize(
                    (tile_size, tile_size), Image.Resampling.LANCZOS)
            x = margin + column * (tile_size + gap)
            panel.paste(tile, (x, y))
            draw.rectangle((x, y, x + 68, y + 28), fill=(0, 0, 0))
            draw.text((x + 7, y + 4), blind_id, fill="white", font=id_font)
        y += tile_size + margin
    return panel


def main(argv=None):
    parser = argparse.ArgumentParser(description="比較VLM用参照パネルを作る")
    parser.add_argument("samples_dir")
    parser.add_argument("output_png")
    parser.add_argument("--metadata-json")
    args = parser.parse_args(argv)
    output_path = Path(args.output_png)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    build_panel(args.samples_dir).save(output_path)
    metadata_path = Path(args.metadata_json) if args.metadata_json else \
        output_path.with_suffix(".json")
    metadata_path.write_text(json.dumps({
        "stage": "development",
        "acceptable_reference_ids": list(DEFAULT_ACCEPTABLE),
        "unacceptable_reference_ids": list(DEFAULT_UNACCEPTABLE),
        "source_samples_dir": str(Path(args.samples_dir).resolve()),
        "note": "References selected only from the development set; do not use as holdout samples.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Panel: {output_path.resolve()}")
    print(f"Metadata: {metadata_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
