import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import convert_glb_to_gltf as converter


TEST_ROOT = Path(__file__).parent


def write_png_header(path: Path, width: int, height: int) -> None:
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height)
    )


def write_valid_gltf(gltf_path: Path, width: int = 2048, height: int = 1024) -> None:
    gltf_path.parent.mkdir(parents=True, exist_ok=True)
    (gltf_path.parent / "asset.bin").write_bytes(b"bin")
    write_png_header(gltf_path.parent / "baseColor_1.png", width, height)
    gltf_path.write_text(
        json.dumps(
            {
                "images": [{"uri": "baseColor_1.png"}],
                "buffers": [{"uri": "asset.bin"}],
            }
        ),
        encoding="utf-8",
    )


class ConvertGlbToGltfTests(unittest.TestCase):
    def test_find_glb_files_filters_and_sorts_names(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temporary_dir:
            input_dir = Path(temporary_dir)
            for name in ("z.glb", "A.GLB", "ignore.txt", "b.glb"):
                (input_dir / name).touch()

            self.assertEqual(
                ["A.GLB", "b.glb", "z.glb"],
                [path.name for path in converter.find_glb_files(input_dir)],
            )

    def test_convert_one_creates_folder_and_records_png_size(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temporary_dir:
            root = Path(temporary_dir)
            source = root / "input" / "desk_v1.glb"
            source.parent.mkdir()
            source.touch()
            output_dir = root / "output"

            def fake_run(command, check):
                self.assertTrue(check)
                gltf_path = Path(command[-1])
                self.assertTrue(gltf_path.parent.is_dir())
                write_valid_gltf(gltf_path, width=4096, height=2048)

            with patch.object(converter.subprocess, "run", side_effect=fake_run):
                result = converter.convert_one(Path("gltf-transform.cmd"), source, output_dir)

            self.assertEqual(
                output_dir / "desk_v1" / "desk_v1.gltf",
                Path(result["output_gltf"]),
            )
            self.assertEqual(4096, result["images"][0]["width"])
            self.assertEqual(2048, result["images"][0]["height"])

    def test_verify_gltf_rejects_missing_referenced_file(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temporary_dir:
            gltf_path = Path(temporary_dir) / "asset.gltf"
            gltf_path.write_text(
                json.dumps(
                    {
                        "images": [{"uri": "missing.png"}],
                        "buffers": [{"uri": "missing.bin"}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(converter.ConversionError, "ファイルがありません"):
                converter.verify_gltf(gltf_path)

    def test_run_batch_continues_after_one_failure_and_writes_manifest(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temporary_dir:
            root = Path(temporary_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            for name in ("a.glb", "b.glb", "c.glb"):
                (input_dir / name).touch()

            def fake_convert(_executable, glb_path, _output_dir):
                if glb_path.name == "b.glb":
                    raise converter.ConversionError("テスト用の失敗")
                return {"output_gltf": f"{glb_path.stem}.gltf", "images": [], "buffers": []}

            with patch.object(converter, "convert_one", side_effect=fake_convert):
                manifest = converter.run_batch(
                    input_dir, output_dir, Path("gltf-transform.cmd"), skip_existing=False
                )

            self.assertEqual({"success": 2, "skipped": 0, "failed": 1}, manifest["summary"])
            self.assertEqual(
                ["success", "failed", "success"],
                [asset["status"] for asset in manifest["assets"]],
            )
            saved = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest, saved)

    def test_skip_existing_verifies_and_records_dimensions(self):
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as temporary_dir:
            root = Path(temporary_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            (input_dir / "desk.glb").touch()
            write_valid_gltf(output_dir / "desk" / "desk.gltf", width=1024, height=1024)

            with patch.object(converter, "convert_one") as convert_one:
                manifest = converter.run_batch(
                    input_dir, output_dir, Path("gltf-transform.cmd"), skip_existing=True
                )

            convert_one.assert_not_called()
            self.assertEqual({"success": 0, "skipped": 1, "failed": 0}, manifest["summary"])
            self.assertEqual(1024, manifest["assets"][0]["images"][0]["width"])
            self.assertEqual("skipped", manifest["assets"][0]["status"])

    @patch.object(converter.shutil, "which", return_value=None)
    def test_find_gltf_transform_has_clear_error(self, _which):
        with self.assertRaisesRegex(converter.ConversionError, "PATHに見つかりません"):
            converter.find_gltf_transform()

    def test_main_returns_one_when_any_asset_failed(self):
        failed_manifest = {"summary": {"success": 1, "skipped": 0, "failed": 1}}
        with (
            patch.object(converter, "find_gltf_transform", return_value=Path("tool.cmd")),
            patch.object(converter, "run_batch", return_value=failed_manifest),
        ):
            exit_code = converter.main(["--input-dir", "in", "--output-dir", "out"])

        self.assertEqual(1, exit_code)


if __name__ == "__main__":
    unittest.main()
