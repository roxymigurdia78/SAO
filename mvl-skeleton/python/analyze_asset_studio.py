"""AssetStudioCaptureの単体画像からディテール量を計算する。

合否は判定しない。背景と輪郭を除外し、固定サイズへ正規化した画像から
Laplacian分散とGLCM contrastをCSVへ記録する。
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import numpy as np
from PIL import Image

try:
    from skimage.feature import graycoprops
    from skimage.filters import laplace
    from skimage.morphology import disk, erosion
    from skimage.transform import resize
except ImportError as error:  # pragma: no cover - 実行環境の案内用
    raise SystemExit(
        "scikit-image が必要です。"
        "python -m pip install -r requirements.txt を実行してください。"
    ) from error


AZIMUTH_PATTERN = re.compile(r"^azimuth_(\d{3})\.png$", re.IGNORECASE)
CSV_FIELDS = (
    "asset",
    "label",
    "azimuth",
    "mask_pixel_count",
    "laplacian_var",
    "glcm_contrast",
)
BACKGROUND_RGB = np.array([0.5, 0.5, 0.5], dtype=np.float32)
EXPECTED_AZIMUTHS = {0, 45, 90, 135, 180, 225, 270, 315}
VERSION_PATTERN = re.compile(r"^(?P<class_name>.+)_v(?P<version>[123])$")


def parse_variant_name(directory: Path) -> tuple[str, str]:
    """<asset>__<label>を分解する。label無しの出力にも対応する。"""
    if "__" not in directory.name:
        return directory.name, ""
    asset, label = directory.name.rsplit("__", 1)
    return asset, label


def find_variant_directories(input_dir: Path) -> list[Path]:
    """出力ルート、または単一variantフォルダから検査対象を列挙する。"""
    if any(AZIMUTH_PATTERN.match(path.name) for path in input_dir.glob("*.png")):
        return [input_dir]
    directories = [
        directory
        for directory in input_dir.iterdir()
        if directory.is_dir()
        and any(
            AZIMUTH_PATTERN.match(path.name)
            for path in directory.glob("*.png")
        )
    ]
    if not directories:
        raise FileNotFoundError(
            f"azimuth_XXX.png を含むフォルダがありません: {input_dir}"
        )
    return sorted(directories, key=lambda path: path.name.lower())


def foreground_mask(
    rgb: np.ndarray,
    background_threshold: float = 0.08,
    erode_pixels: int = 4,
) -> np.ndarray:
    """中性グレー背景を除外し、輪郭の影響を避けるためマスクを収縮する。"""
    distance = np.linalg.norm(rgb - BACKGROUND_RGB, axis=2)
    mask = distance > background_threshold
    return eroded_mask(mask, erode_pixels)


def eroded_mask(mask: np.ndarray, erode_pixels: int) -> np.ndarray:
    """輪郭の影響を除くため、二値マスクを指定画素数だけ収縮する。"""
    if erode_pixels > 0:
        mask = erosion(mask, footprint=disk(erode_pixels))
    if not np.any(mask):
        raise ValueError(
            "背景除外後の画素がありません。background_thresholdを確認してください。"
        )
    return mask


def captured_mask(
    mask_path: Path, expected_shape: tuple[int, int], erode_pixels: int
) -> np.ndarray:
    """AssetStudioCaptureの白黒マスクを読み込み、二値化して収縮する。"""
    with Image.open(mask_path) as image:
        mask_image = np.asarray(image.convert("L"), dtype=np.uint8)
    if mask_image.shape != expected_shape:
        raise ValueError(
            f"通常画像とマスク画像のサイズが一致しません: {mask_path} "
            f"expected={expected_shape}, actual={mask_image.shape}"
        )
    return eroded_mask(mask_image >= 128, erode_pixels)


def normalized_crop(
    rgb: np.ndarray, mask: np.ndarray, size: int = 256
) -> tuple[np.ndarray, np.ndarray]:
    """マスクの外接矩形を切り出し、画像とマスクを固定サイズへ変換する。"""
    ys, xs = np.nonzero(mask)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    rgb_crop = rgb[y0:y1, x0:x1]
    mask_crop = mask[y0:y1, x0:x1]

    normalized_rgb = resize(
        rgb_crop,
        (size, size, 3),
        order=1,
        mode="reflect",
        anti_aliasing=True,
        preserve_range=True,
    ).astype(np.float32)
    normalized_mask = resize(
        mask_crop.astype(np.uint8),
        (size, size),
        order=0,
        mode="edge",
        anti_aliasing=False,
        preserve_range=True,
    ) >= 0.5
    if not np.any(normalized_mask):
        raise ValueError("リサイズ後のforeground maskが空です。")
    return normalized_rgb, normalized_mask


def masked_glcm_contrast(
    gray: np.ndarray, mask: np.ndarray, levels: int = 256
) -> float:
    """有効画素同士の4方向GLCM contrastの平均を返す。"""
    quantized = np.clip(
        np.rint(gray * (levels - 1)), 0, levels - 1
    ).astype(np.uint8)
    # 距離1、0/45/90/135度。画像座標ではyが下向きだがcontrastには影響しない。
    offsets = ((0, 1), (-1, 1), (-1, 0), (-1, -1))
    glcm = np.zeros((levels, levels, 1, len(offsets)), dtype=np.uint32)

    height, width = gray.shape
    for index, (dy, dx) in enumerate(offsets):
        source_y = slice(max(0, -dy), min(height, height - dy))
        source_x = slice(max(0, -dx), min(width, width - dx))
        target_y = slice(max(0, dy), min(height, height + dy))
        target_x = slice(max(0, dx), min(width, width + dx))
        valid = mask[source_y, source_x] & mask[target_y, target_x]
        if not np.any(valid):
            raise ValueError("GLCMを計算できる隣接画素がありません。")
        source = quantized[source_y, source_x][valid]
        target = quantized[target_y, target_x][valid]
        np.add.at(glcm[:, :, 0, index], (source, target), 1)
        # 対称GLCMとして逆向きの組も加える。
        np.add.at(glcm[:, :, 0, index], (target, source), 1)

    return float(graycoprops(glcm, "contrast").mean())


def detail_metrics(
    path: Path,
    background_threshold: float = 0.08,
    erode_pixels: int = 4,
    size: int = 256,
) -> dict[str, float | int]:
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0

    mask_path = path.with_name(f"{path.stem}_mask.png")
    if mask_path.is_file():
        mask = captured_mask(mask_path, rgb.shape[:2], erode_pixels)
    else:
        # 旧形式の撮影結果だけ、背景グレーとの色距離へフォールバックする。
        mask = foreground_mask(rgb, background_threshold, erode_pixels)
    mask_pixel_count = int(np.count_nonzero(mask))
    normalized_rgb, normalized_mask = normalized_crop(rgb, mask, size)
    gray = np.tensordot(
        normalized_rgb,
        np.array([0.2126, 0.7152, 0.0722], dtype=np.float32),
        axes=([2], [0]),
    ).astype(np.float32)

    laplacian_values = laplace(gray)[normalized_mask]
    return {
        "mask_pixel_count": mask_pixel_count,
        "laplacian_var": float(np.var(laplacian_values)),
        "glcm_contrast": masked_glcm_contrast(gray, normalized_mask),
    }


def analyze_directory(
    input_dir: Path,
    output_csv: Path,
    background_threshold: float = 0.08,
    erode_pixels: int = 4,
    size: int = 256,
) -> list[dict[str, str | float | int]]:
    rows: list[dict[str, str | float | int]] = []
    for directory in find_variant_directories(input_dir):
        asset, label = parse_variant_name(directory)
        images = sorted(
            path
            for path in directory.glob("*.png")
            if AZIMUTH_PATTERN.match(path.name)
        )
        actual_azimuths = {
            int(AZIMUTH_PATTERN.match(path.name).group(1))  # type: ignore[union-attr]
            for path in images
        }
        if actual_azimuths != EXPECTED_AZIMUTHS:
            missing = sorted(EXPECTED_AZIMUTHS - actual_azimuths)
            extra = sorted(actual_azimuths - EXPECTED_AZIMUTHS)
            raise ValueError(
                f"8方位が揃っていません: {directory} "
                f"missing={missing}, extra={extra}"
            )
        for path in images:
            match = AZIMUTH_PATTERN.match(path.name)
            assert match is not None
            metrics = detail_metrics(
                path, background_threshold, erode_pixels, size
            )
            rows.append(
                {
                    "asset": asset,
                    "label": label,
                    "azimuth": int(match.group(1)),
                    "mask_pixel_count": metrics["mask_pixel_count"],
                    "laplacian_var": round(float(metrics["laplacian_var"]), 10),
                    "glcm_contrast": round(float(metrics["glcm_contrast"]), 6),
                }
            )

    if not rows:
        raise FileNotFoundError(f"検査対象画像がありません: {input_dir}")
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def print_label_medians(rows: list[dict[str, str | float | int]]) -> None:
    groups: dict[tuple[str, str], list[dict[str, str | float | int]]] = {}
    for row in rows:
        key = (str(row["asset"]), str(row["label"]))
        groups.setdefault(key, []).append(row)

    print("\nlabel別 8方向中央値")
    print(
        f"{'asset':<24} {'label':<16} {'views':>5} "
        f"{'laplacian_var':>16} {'glcm_contrast':>16}"
    )
    for (asset, label), values in sorted(groups.items()):
        laplacians = [float(row["laplacian_var"]) for row in values]
        contrasts = [float(row["glcm_contrast"]) for row in values]
        print(
            f"{asset:<24} {label or '(none)':<16} {len(values):>5d} "
            f"{float(np.median(laplacians)):>16.10f} "
            f"{float(np.median(contrasts)):>16.6f}"
        )


def summarize_laplacian(
    rows: list[dict[str, str | float | int]],
) -> list[dict[str, str | float | int]]:
    """assetとlabelごとに8方向のLaplacian統計を集計する。"""
    groups: dict[tuple[str, str], list[dict[str, str | float | int]]] = {}
    for row in rows:
        key = (str(row["asset"]), str(row["label"]))
        groups.setdefault(key, []).append(row)

    summaries: list[dict[str, str | float | int]] = []
    for (asset, label), values in sorted(groups.items()):
        minimum = min(values, key=lambda row: float(row["laplacian_var"]))
        maximum = max(values, key=lambda row: float(row["laplacian_var"]))
        summaries.append(
            {
                "asset": asset,
                "label": label,
                "views": len(values),
                "median": float(
                    np.median([float(row["laplacian_var"]) for row in values])
                ),
                "minimum": float(minimum["laplacian_var"]),
                "minimum_azimuth": int(minimum["azimuth"]),
                "maximum": float(maximum["laplacian_var"]),
                "maximum_azimuth": int(maximum["azimuth"]),
            }
        )
    return summaries


def print_asset_laplacian_summary(
    summaries: list[dict[str, str | float | int]],
) -> None:
    print("\nアセット別 Laplacian 8方向集計")
    print(
        f"{'asset':<28} {'views':>5} {'median':>14} "
        f"{'minimum':>14} {'az':>4} {'maximum':>14} {'az':>4}"
    )
    for summary in summaries:
        asset = str(summary["asset"])
        label = str(summary["label"])
        display_name = asset if not label else f"{asset}__{label}"
        print(
            f"{display_name:<28} {int(summary['views']):>5d} "
            f"{float(summary['median']):>14.10f} "
            f"{float(summary['minimum']):>14.10f} "
            f"{int(summary['minimum_azimuth']):>4d} "
            f"{float(summary['maximum']):>14.10f} "
            f"{int(summary['maximum_azimuth']):>4d}"
        )


def print_class_version_table(
    summaries: list[dict[str, str | float | int]],
) -> None:
    """同じクラスのv1/v2/v3についてLaplacian中央値を横並び表示する。"""
    groups: dict[tuple[str, str], dict[int, float]] = {}
    for summary in summaries:
        match = VERSION_PATTERN.match(str(summary["asset"]))
        if match is None:
            continue
        key = (match.group("class_name"), str(summary["label"]))
        groups.setdefault(key, {})[int(match.group("version"))] = float(
            summary["median"]
        )

    if not groups:
        return

    print("\n同一クラス v1/v2/v3 Laplacian中央値")
    print(f"{'class':<24} {'label':<14} {'v1':>14} {'v2':>14} {'v3':>14}")
    for (class_name, label), versions in sorted(groups.items()):
        values = [
            f"{versions[version]:>14.10f}"
            if version in versions
            else f"{'-':>14}"
            for version in (1, 2, 3)
        ]
        print(
            f"{class_name:<24} {label or '(none)':<14} "
            + " ".join(values)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AssetStudioCapture画像のディテール量をCSVへ出力する"
    )
    parser.add_argument(
        "input_dir", type=Path, help="AssetStudioCaptureの出力ルート"
    )
    parser.add_argument(
        "--output", type=Path, help="出力CSV（既定: 入力ルート/asset_studio_metrics.csv）"
    )
    parser.add_argument("--background-threshold", type=float, default=0.08)
    parser.add_argument("--erode-pixels", type=int, default=4)
    parser.add_argument("--size", type=int, default=256)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    if not input_dir.is_dir():
        raise FileNotFoundError(f"入力フォルダがありません: {input_dir}")
    if not 0.0 <= args.background_threshold <= np.sqrt(3.0):
        raise ValueError("background-thresholdは0以上sqrt(3)以下にしてください。")
    if args.erode_pixels < 0:
        raise ValueError("erode-pixelsは0以上にしてください。")
    if args.size < 8:
        raise ValueError("sizeは8以上にしてください。")

    output = (
        args.output.resolve()
        if args.output
        else input_dir / "asset_studio_metrics.csv"
    )
    rows = analyze_directory(
        input_dir,
        output,
        args.background_threshold,
        args.erode_pixels,
        args.size,
    )
    print_label_medians(rows)
    summaries = summarize_laplacian(rows)
    print_asset_laplacian_summary(summaries)
    print_class_version_table(summaries)
    print(f"\nImages: {len(rows)}")
    print(f"CSV   : {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
