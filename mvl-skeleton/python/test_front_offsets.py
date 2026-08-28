import unittest
from unittest.mock import patch

import numpy as np

import front_offsets


class FrontOffsetTests(unittest.TestCase):
    def test_chair_front_is_opposite_upper_backrest_bias(self):
        # 上部が-Zへ偏る椅子は、反対の+Zが正面=0度。
        vertices = np.array([
            [-1, 0, -1], [1, 0, 1], [-0.5, 1, -0.9], [0.5, 1, -0.9],
        ], dtype=float)
        with patch("front_offsets.contact_offset.load_mesh",
                   return_value=(vertices, np.empty((0, 3), dtype=int))):
            result = front_offsets.estimate_asset("chair_v1.glb", "chair")
        self.assertEqual(0.0, result["front_offset_deg"])
        self.assertEqual("upper_mesh_asymmetry", result["front_offset_method"])

    def test_manual_asset_override_has_priority(self):
        result = front_offsets.estimate_asset(
            "cabinet_v1.glb", "cabinet", {
                "assets": {"cabinet_v1.glb": {
                    "front_offset_deg": 270, "note": "four-view confirmation"}},
                "classes": {"cabinet": 90},
            })
        self.assertEqual(270.0, result["front_offset_deg"])
        self.assertEqual("manual_override", result["front_offset_method"])

    def test_directionless_class_is_explicitly_not_applicable(self):
        result = front_offsets.estimate_asset("rug_v1.glb", "rug")
        self.assertEqual(0.0, result["front_offset_deg"])
        self.assertEqual("not_applicable", result["front_offset_method"])

    def test_ambiguous_directional_class_is_reported_unresolved(self):
        result = front_offsets.estimate_asset("printer_v1.glb", "printer")
        self.assertIsNone(result["front_offset_deg"])
        self.assertEqual("unresolved", result["front_offset_method"])


if __name__ == "__main__":
    unittest.main()
