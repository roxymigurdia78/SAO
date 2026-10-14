from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from analyze_texel_density import (
    read_khronos_reference,
    texels_per_meter,
    weighted_quantile,
)


class TexelDensityTest(unittest.TestCase):
    def test_unit_triangle_matches_texture_resolution(self) -> None:
        triangles_3d = np.array(
            [[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]]
        )
        triangles_uv = np.array(
            [[[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]]
        )
        result = texels_per_meter(triangles_3d, triangles_uv, 100, 100)
        self.assertAlmostEqual(float(result[0]), 100.0)

    def test_non_uniform_scale_changes_physical_area(self) -> None:
        triangles_3d = np.array(
            [[[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 1.0, 0.0]]]
        )
        triangles_uv = np.array(
            [[[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]]
        )
        result = texels_per_meter(triangles_3d, triangles_uv, 100, 100)
        self.assertAlmostEqual(float(result[0]), np.sqrt(5000.0))

    def test_weighted_quantile_uses_surface_area(self) -> None:
        values = np.array([100.0, 200.0, 300.0])
        areas = np.array([8.0, 1.0, 1.0])
        self.assertEqual(weighted_quantile(values, areas, 0.10), 100.0)
        self.assertEqual(weighted_quantile(values, areas, 0.50), 100.0)

    def test_zero_uv_is_zero_density(self) -> None:
        triangles_3d = np.array(
            [[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]]
        )
        triangles_uv = np.zeros((1, 3, 2), dtype=np.float64)
        result = texels_per_meter(triangles_3d, triangles_uv, 1024, 1024)
        self.assertEqual(float(result[0]), 0.0)

    def test_khronos_area_density_is_converted_with_square_root(self) -> None:
        report = {
            "version": "1.0.4",
            "textures": {
                "width": {"maximum": {"value": 100}},
                "height": {"maximum": {"value": 100}},
            },
            "uvs": {"pixelsPerMeter": {"maximum": {"value": 4.0}}},
            "product": {
                "overallDimensions": {
                    "length": {"value": 1.0},
                    "width": {"value": 2.0},
                    "height": {"value": 3.0},
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            result = read_khronos_reference(path)
        self.assertEqual(result["auditor_console_area_density_px2_per_m2"], 40000.0)
        self.assertEqual(result["sqrt_conversion_px_per_m"], 200.0)


if __name__ == "__main__":
    unittest.main()
