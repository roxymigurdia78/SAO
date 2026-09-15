import unittest
from unittest.mock import patch

import machine_checks as mc
from make_floating_eval_scenes import FLOATING_TARGETS, inject_floating_defects


def sample_scene():
    def obj(object_id, y, height, rests_on=None):
        value = {
            "id": object_id,
            "asset": f"{object_id.removesuffix('_01')}_v1.glb",
            "position": [1.0, y, 1.0],
            "rotation_y_deg": 0.0,
            "target_dimensions": {"width": 0.4, "height": height, "depth": 0.4},
        }
        if rests_on:
            value["rests_on"] = rests_on
        return value

    return {
        "scene_id": "test",
        "assets_dir": "assets",
        "room": {"floor_y": 0.0},
        "objects": [
            obj("desk_01", 0.20, 0.70),
            obj("chair_01", 0.40, 0.90),
            obj("backpack_01", 0.25, 0.45),
            obj("monitor_01", 1.30, 0.40, "desk_01"),
            obj("laptop_01", 1.10, 0.24, "desk_01"),
            obj("mug_01", 1.50, 0.12, "desk_01"),
        ],
    }


class FloatingEvalSceneTests(unittest.TestCase):
    @patch("machine_checks.co.needs_review", return_value=False)
    @patch("machine_checks.co.lookup", return_value=0.0)
    def test_normalizes_baseline_and_injects_exactly_four(self, _lookup, _review):
        source = sample_scene()
        result = inject_floating_defects(source, (0.05, 0.15, 0.30, 0.50))
        violations = mc.check_floating(result, mc.collect_aabbs(result))
        positive_ids = {v["object_id"] for v in violations if v["type"] == "floating"}
        self.assertEqual(set(FLOATING_TARGETS), positive_ids)
        self.assertEqual(4, result["evaluation_injection"]["expected_positive_count"])

    @patch("machine_checks.co.needs_review", return_value=False)
    @patch("machine_checks.co.lookup", return_value=0.0)
    def test_does_not_modify_source_scene(self, _lookup, _review):
        source = sample_scene()
        original_y = [obj["position"][1] for obj in source["objects"]]
        inject_floating_defects(source, (0.05, 0.15, 0.30, 0.50))
        self.assertEqual(original_y, [obj["position"][1] for obj in source["objects"]])


if __name__ == "__main__":
    unittest.main()
