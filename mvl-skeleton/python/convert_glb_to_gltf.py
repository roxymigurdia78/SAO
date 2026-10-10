"""GLBをUnityで扱いやすい外部glTF・BIN・PNGへ一括変換する。"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


class ConversionError(RuntimeError):
    """変換または出力検証に失敗したときのエラー。"""


# 入力GLBの検索 ---------------------------------------------------------------
def find_glb_files(input_dir: Path) -> list[Path]:
    """入力直下のGLBを、大文字小文字を区別しない名前順で返す。"""
    if not input_dir.is_dir():
        raise ConversionError(f"入力フォルダがありません: {input_dir}")

    glb_files = [
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".glb"
    ]
    return sorted(glb_files, key=lambda path: (path.name.casefold(), path.name))


# gltf-transformの探索 --------------------------------------------------------
def find_gltf_transform() -> Path:
    """Windowsの.cmdを含め、PATHからgltf-transformの実体を探す。"""
    executable = shutil.which("gltf-transform")
    if executable is None:
        raise ConversionError(
            "gltf-transformがPATHに見つかりません。"
            "'npm install --global @gltf-transform/cli' でインストールした後、"
            "新しいターミナルを開いてください。"
        )
    return Path(executable)


# 変換後ファイルの検証 ---------------------------------------------------------
def _external_file(asset_dir: Path, uri: object, label: str) -> Path:
    """URIが同じ物体フォルダ内の実在ファイルを指していることを確認する。"""
    if not isinstance(uri, str) or not uri.strip():
        raise ConversionError(f"{label} に外部ファイルのuriがありません")

    parsed = urlsplit(uri)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ConversionError(f"{label} がローカルファイルuriではありません: {uri!r}")

    referenced = (asset_dir / Path(unquote(parsed.path))).resolve()
    try:
        referenced.relative_to(asset_dir.resolve())
    except ValueError as exc:
        raise ConversionError(
            f"{label} のuriが物体フォルダの外を指しています: {uri!r}"
        ) from exc

    if not referenced.is_file():
        raise ConversionError(f"{label} のファイルがありません: {referenced}")
    return referenced


def read_png_size(png_path: Path) -> tuple[int, int]:
    """PNGのIHDRから幅と高さを読む。画像全体のデコードは行わない。"""
    try:
        with png_path.open("rb") as file:
            header = file.read(24)
    except OSError as exc:
        raise ConversionError(f"PNGを読めません: {png_path}: {exc}") from exc

    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ConversionError(f"正しいPNGヘッダーではありません: {png_path}")

    width, height = struct.unpack(">II", header[16:24])
    if width == 0 or height == 0:
        raise ConversionError(f"PNGの幅または高さが0です: {png_path}")
    return width, height


def verify_gltf(gltf_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """glTF JSONと、そこから参照されるPNG・BINを検証する。"""
    try:
        with gltf_path.open("r", encoding="utf-8") as file:
            document = json.load(file)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConversionError(f"glTF JSONを読めません: {gltf_path}: {exc}") from exc

    if not isinstance(document, dict):
        raise ConversionError(f"glTFのルートがJSONオブジェクトではありません: {gltf_path}")

    images = document.get("images")
    buffers = document.get("buffers")
    if not isinstance(images, list) or not images:
        raise ConversionError(f"glTFに外部画像がありません: {gltf_path}")
    if not isinstance(buffers, list) or not buffers:
        raise ConversionError(f"glTFに外部バッファがありません: {gltf_path}")

    image_records: list[dict[str, Any]] = []
    for index, item in enumerate(images):
        uri = item.get("uri") if isinstance(item, dict) else None
        image_path = _external_file(gltf_path.parent, uri, f"images[{index}]")
        if image_path.suffix.lower() != ".png":
            raise ConversionError(f"PNG以外の画像が出力されています: {image_path.name}")
        width, height = read_png_size(image_path)
        image_records.append(
            {
                "uri": uri,
                "path": str(image_path),
                "width": width,
                "height": height,
            }
        )

    buffer_records: list[dict[str, Any]] = []
    for index, item in enumerate(buffers):
        uri = item.get("uri") if isinstance(item, dict) else None
        buffer_path = _external_file(gltf_path.parent, uri, f"buffers[{index}]")
        if buffer_path.suffix.lower() != ".bin":
            raise ConversionError(f"BIN以外のバッファが出力されています: {buffer_path.name}")
        buffer_records.append(
            {"uri": uri, "path": str(buffer_path), "size_bytes": buffer_path.stat().st_size}
        )

    return image_records, buffer_records


# 1物体の変換 ------------------------------------------------------------------
def convert_one(executable: Path, glb_path: Path, output_dir: Path) -> dict[str, Any]:
    """1個のGLBを専用フォルダへ変換し、manifest用の情報を返す。"""
    asset_dir = output_dir / glb_path.stem
    asset_dir.mkdir(parents=True, exist_ok=True)
    gltf_path = asset_dir / f"{glb_path.stem}.gltf"

    print(f"変換: {glb_path.name} -> {gltf_path}")
    try:
        subprocess.run(
            [str(executable), "copy", str(glb_path), str(gltf_path)],
            check=True,
        )
    except OSError as exc:
        raise ConversionError(f"gltf-transformを起動できません: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise ConversionError(
            f"gltf-transformが失敗しました（終了コード {exc.returncode}）"
        ) from exc

    images, buffers = verify_gltf(gltf_path)
    print(f"確認済み: {gltf_path.name}（BIN {len(buffers)}個、PNG {len(images)}個）")
    return {
        "output_gltf": str(gltf_path),
        "images": images,
        "buffers": buffers,
    }


def inspect_existing(glb_path: Path, output_dir: Path) -> dict[str, Any] | None:
    """スキップ対象の既存glTFを検証する。存在しなければNoneを返す。"""
    gltf_path = output_dir / glb_path.stem / f"{glb_path.stem}.gltf"
    if not gltf_path.is_file():
        return None

    images, buffers = verify_gltf(gltf_path)
    return {
        "output_gltf": str(gltf_path),
        "images": images,
        "buffers": buffers,
    }


# manifestの保存 ---------------------------------------------------------------
def write_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    """途中で停止しても結果が残るよう、1物体ごとにmanifestを書き直す。"""
    try:
        with manifest_path.open("w", encoding="utf-8") as file:
            json.dump(manifest, file, ensure_ascii=False, indent=2)
            file.write("\n")
    except OSError as exc:
        raise ConversionError(f"manifest.jsonを書けません: {manifest_path}: {exc}") from exc


# 全物体のバッチ処理 -----------------------------------------------------------
def run_batch(
    input_dir: Path,
    output_dir: Path,
    executable: Path,
    skip_existing: bool,
) -> dict[str, Any]:
    glb_files = find_glb_files(input_dir)
    if not glb_files:
        raise ConversionError(f"GLBファイルがありません: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest: dict[str, Any] = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "gltf_transform": str(executable),
        "skip_existing": skip_existing,
        "assets": [],
        "summary": {"success": 0, "skipped": 0, "failed": 0},
    }

    for index, glb_path in enumerate(glb_files, start=1):
        print(f"[{index}/{len(glb_files)}] {glb_path.name}")
        record: dict[str, Any] = {
            "name": glb_path.stem,
            "input_glb": str(glb_path),
        }

        try:
            existing = inspect_existing(glb_path, output_dir) if skip_existing else None
            if existing is not None:
                record.update(existing)
                record["status"] = "skipped"
                manifest["summary"]["skipped"] += 1
                print(f"スキップ: 検証済みの出力があります: {existing['output_gltf']}")
            else:
                record.update(convert_one(executable, glb_path, output_dir))
                record["status"] = "success"
                manifest["summary"]["success"] += 1
        except Exception as exc:
            # 1個が失敗しても、エラーを記録して残りの物体を続行する。
            record["status"] = "failed"
            record["error"] = f"{type(exc).__name__}: {exc}"
            manifest["summary"]["failed"] += 1
            print(f"失敗: {glb_path.name}: {exc}", file=sys.stderr)

        manifest["assets"].append(record)
        write_manifest(manifest_path, manifest)

    return manifest


# コマンドライン入口 -----------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="フォルダ内のGLBを .gltf + .bin + PNG に一括変換します。"
    )
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="検証に通る既存の .gltf + .bin + PNG があれば変換をスキップします。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        executable = find_gltf_transform()
        manifest = run_batch(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            executable=executable,
            skip_existing=args.skip_existing,
        )
    except ConversionError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    summary = manifest["summary"]
    print(
        "完了: "
        f"成功 {summary['success']}、"
        f"スキップ {summary['skipped']}、"
        f"失敗 {summary['failed']}"
    )
    print(f"manifest: {args.output_dir / 'manifest.json'}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
