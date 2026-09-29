import unittest
from unittest.mock import patch

import numpy as np

import front_offsets


class FrontOffsetTests(unittest.TestCase):
    def test_laptop_vlm_response_requires_opposite_hinge_side(self):
        result = front_offsets._validate_vlm_front_response({
            "front_offset_deg": 0,
            "hinge_side_deg": 180,
            "confidence": 0.9,
            "reason": "base extends from the hinge toward +Z",
        }, "laptop")
        self.assertEqual(0, result["front_offset_deg"])

    def test_laptop_vlm_response_rejects_screen_side_as_front(self):
        with self.assertRaisesRegex(ValueError, "180度反対"):
            front_offsets._validate_vlm_front_response({
                "front_offset_deg": 180,
                "hinge_side_deg": 180,
                "confidence": 0.9,
                "reason": "screen is visible",
            }, "laptop")

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

    def test_laptop_front_is_keyboard_side_opposite_screen_bias(self):
        # 画面が-Z側にあるノートPCは、使用者・キーボード側の+Zが正面=0度。
        vertices = np.array([
            [-1, 0, -1], [1, 0, 1], [-0.5, 1, -0.9], [0.5, 1, -0.9],
        ], dtype=float)
        with patch("front_offsets.contact_offset.load_mesh",
                   return_value=(vertices, np.empty((0, 3), dtype=int))):
            result = front_offsets.estimate_asset("laptop_v1.glb", "laptop")
        self.assertEqual(0.0, result["front_offset_deg"])
        self.assertEqual("semantic_geometry_rule", result["front_offset_method"])

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

    @patch("front_offsets.vlm_estimate_asset")
    @patch("front_offsets.render_turntable")
    @patch("front_offsets.estimate_asset")
    def test_directional_verification_accepts_independent_agreement(
            self, estimate, _render, vlm):
        estimate.return_value = {
            "front_offset_deg": 90.0,
            "front_offset_method": "upper_mesh_asymmetry",
            "front_offset_confidence": 0.4,
            "front_offset_note": "mesh",
        }
        vlm.return_value = {
            "front_offset_deg": 90, "confidence": 0.9,
            "reason": "screen side", "votes": "3/3",
        }
        inventory = {"assets": [{"file": "monitor_v1.glb", "class": "monitor"}]}
        with patch("pathlib.Path.read_text", return_value=__import__("json").dumps(inventory)), \
                patch("pathlib.Path.write_text"):
            report = front_offsets.update_inventory(
                "assets", inventory_path="inventory.json",
                overrides_path="missing.json", report_path="report.json",
                vlm_attempts=3, vlm_verify_directional=True)
        self.assertEqual("heuristic_vlm_agreement",
                         report["results"][0]["front_offset_method"])
        self.assertEqual(90.0, report["results"][0]["front_offset_deg"])

    @patch("front_offsets.vlm_estimate_asset")
    @patch("front_offsets.render_turntable")
    @patch("front_offsets.estimate_asset")
    def test_trusted_semantic_geometry_survives_vlm_conflict(
            self, estimate, _render, vlm):
        estimate.return_value = {
            "front_offset_deg": 180.0,
            "front_offset_method": "semantic_geometry_rule",
            "front_offset_confidence": 0.48,
            "front_offset_note": "mesh",
        }
        vlm.return_value = {
            "front_offset_deg": 0, "confidence": 0.95,
            "reason": "keyboard user side", "votes": "3/3",
        }
        inventory = {"assets": [{"file": "future_laptop.glb", "class": "laptop"}]}
        with patch("pathlib.Path.read_text", return_value=__import__("json").dumps(inventory)), \
                patch("pathlib.Path.write_text"):
            report = front_offsets.update_inventory(
                "assets", inventory_path="inventory.json",
                overrides_path="missing.json", report_path="report.json",
                vlm_attempts=3, vlm_verify_directional=True)
        self.assertEqual("semantic_geometry_vlm_disagreement",
                         report["results"][0]["front_offset_method"])
        self.assertEqual(180.0, report["results"][0]["front_offset_deg"])

    @patch("front_offsets.estimate_asset")
    def test_existing_vlm_consensus_is_not_erased(self, estimate):
        estimate.return_value = {
            "front_offset_deg": None,
            "front_offset_method": "unresolved",
            "front_offset_confidence": "unresolved",
            "front_offset_note": "mesh inconclusive",
        }
        inventory = {"assets": [{
            "file": "desk_v1.glb", "class": "desk",
            "front_offset_deg": 0.0,
            "front_offset_method": "vlm_turntable_consensus",
            "front_offset_confidence": 0.9,
            "front_offset_note": "drawers visible (VLM votes=3/3)",
        }]}
        with patch("pathlib.Path.read_text", return_value=__import__("json").dumps(inventory)), \
                patch("pathlib.Path.write_text"):
            report = front_offsets.update_inventory(
                "assets", inventory_path="inventory.json",
                overrides_path="missing.json", report_path="report.json")
        self.assertEqual("vlm_turntable_consensus",
                         report["results"][0]["front_offset_method"])


if __name__ == "__main__":
    unittest.main()
