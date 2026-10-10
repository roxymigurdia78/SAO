"""タイル画像の反対側の端を比較し、継ぎ目候補を数値化する。

合否閾値は決めない。CSVと2x2反復プレビューを作り、人の目による
「自然 / ずれあり」ラベルと数値を対応させるための基礎データを出す。
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def _mean_rgb_distance(a: np.ndarray, b: np.ndarray) -> float:
    """対応画素間のRGBユークリッド距離を0..1で返す。"""
    distance = np.linalg.norm(a - b, axis=2) / np.sqrt(3.0)
    return float(distance.mean())


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    """1次元プロフィール間の相関。変化が無い場合は0を返す。"""
    if float(a.std()) < 1e-8 or float(b.std()) < 1e-8:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def seam_metrics(path: Path, band_width: int = 8) -> dict[str, float | int | str]:
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0

    height, width, _ = rgb.shape
    if width < 3 or height < 3:
        raise ValueError(f"画像が小さすぎます: {path} ({width}x{height})")
    band = max(1, min(band_width, width // 2, height // 2))

    # 画像をRepeatしたときに直接隣り合う、反対側の端の不連続量。
    lr_edge = _mean_rgb_distance(rgb[:, -1:, :], rgb[:, :1, :])
    tb_edge = _mean_rgb_distance(rgb[-1:, :, :], rgb[:1, :, :])

    # 高周波な材質を一律に不利にしないため、画像内部の通常の隣接差で正規化する。
    lr_internal = _mean_rgb_distance(rgb[:, 1:, :], rgb[:, :-1, :])
    tb_internal = _mean_rgb_distance(rgb[1:, :, :], rgb[:-1, :, :])
    epsilon = 1e-8

    # 端の1列が偶然一致しても、端付近に明るさの帯があると反復時に目立つ。
    lr_band = float(np.linalg.norm(
        rgb[:, :band, :].mean(axis=(0, 1))
        - rgb[:, -band:, :].mean(axis=(0, 1))) / np.sqrt(3.0))
    tb_band = float(np.linalg.norm(
        rgb[:band, :, :].mean(axis=(0, 1))
        - rgb[-band:, :, :].mean(axis=(0, 1))) / np.sqrt(3.0))

    # レンガなどの規則模様向け補助列。端付近の輝度模様が同じ位相で
    # 繰り返されていないかを見る。材質を問わない合否値にはしない。
    luminance = np.tensordot(
        rgb, np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axes=([2], [0]))
    lr_profile_correlation = _correlation(
        luminance[:, :band].mean(axis=1),
        luminance[:, -band:].mean(axis=1))
    tb_profile_correlation = _correlation(
        luminance[:band, :].mean(axis=0),
        luminance[-band:, :].mean(axis=0))

    lr_ratio = lr_edge / max(lr_internal, epsilon)
    tb_ratio = tb_edge / max(tb_internal, epsilon)
    return {
        "file": path.name,
        "width": width,
        "height": height,
        "band_width": band,
        "lr_edge_distance": round(lr_edge, 6),
        "lr_internal_distance": round(lr_internal, 6),
        "lr_edge_ratio": round(lr_ratio, 6),
        "lr_band_mean_distance": round(lr_band, 6),
        "tb_edge_distance": round(tb_edge, 6),
        "tb_internal_distance": round(tb_internal, 6),
        "tb_edge_ratio": round(tb_ratio, 6),
        "tb_band_mean_distance": round(tb_band, 6),
        "lr_band_profile_correlation": round(lr_profile_correlation, 6),
        "tb_band_profile_correlation": round(tb_profile_correlation, 6),
        "max_edge_ratio": round(max(lr_ratio, tb_ratio), 6),
    }


def save_tiled_preview(source: Path, destination: Path, tile_size: int = 512) -> None:
    with Image.open(source) as image:
        tile = image.convert("RGB")
        tile.thumbnail((tile_size, tile_size), Image.Resampling.LANCZOS)
        preview = Image.new("RGB", (tile.width * 2, tile.height * 2))
        for y in (0, tile.height):
            for x in (0, tile.width):
                preview.paste(tile, (x, y))
        destination.parent.mkdir(parents=True, exist_ok=True)
        preview.save(destination)


def save_review_sheet(rows: list[dict], preview_dir: Path,
                      destination: Path, columns: int = 3) -> None:
    panel_width, image_height, label_height = 360, 320, 42
    panel_height = image_height + label_height
    row_count = (len(rows) + columns - 1) // columns
    sheet = Image.new(
        "RGB", (panel_width * columns, panel_height * row_count), "white")
    draw = ImageDraw.Draw(sheet)

    for index, row in enumerate(rows):
        x = (index % columns) * panel_width
        y = (index // columns) * panel_height
        preview_path = preview_dir / f"{Path(row['file']).stem}_2x2.png"
        with Image.open(preview_path) as image:
            preview = image.convert("RGB")
            preview.thumbnail((panel_width, image_height), Image.Resampling.LANCZOS)
            image_x = x + (panel_width - preview.width) // 2
            sheet.paste(preview, (image_x, y))
        label = (f"{row['file']}  LR={row['lr_edge_ratio']:.2f}  "
                 f"TB={row['tb_edge_ratio']:.2f}")
        draw.text((x + 8, y + image_height + 10), label, fill="black")

    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)


def analyze_directory(input_dir: Path, output_csv: Path, preview_dir: Path,
                      pattern: str = "*.png", band_width: int = 8,
                      review_sheet: Path | None = None) -> list[dict]:
    review_path = review_sheet or input_dir / "seam_review.png"
    files = sorted(
        path for path in input_dir.glob(pattern)
        if path.resolve() != review_path.resolve())
    if not files:
        raise FileNotFoundError(f"検査対象画像がありません: {input_dir / pattern}")

    rows = []
    for path in files:
        row = seam_metrics(path, band_width=band_width)
        rows.append(row)
        save_tiled_preview(path, preview_dir / f"{path.stem}_2x2.png")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    save_review_sheet(rows, preview_dir, review_path)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="タイル画像の左右・上下の継ぎ目スコアと2x2プレビューを作る")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--pattern", default="*.png")
    parser.add_argument("--band-width", type=int, default=8)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--preview-dir", type=Path)
    parser.add_argument("--review-sheet", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output = (args.output or input_dir / "seam_metrics.csv").resolve()
    previews = (args.preview_dir or input_dir / "seam_previews").resolve()
    review_sheet = (
        args.review_sheet or input_dir / "seam_review.png").resolve()
    rows = analyze_directory(
        input_dir, output, previews, args.pattern, args.band_width, review_sheet)
    print(f"Images : {len(rows)}")
    print(f"CSV    : {output}")
    print(f"Preview: {previews}")
    print(f"Review : {review_sheet}")
    for row in rows:
        print(f"  {row['file']}: LR={row['lr_edge_ratio']:.3f}, "
              f"TB={row['tb_edge_ratio']:.3f}, max={row['max_edge_ratio']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
