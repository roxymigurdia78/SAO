import unittest

import machine_checks as mc
from make_orientation_eval_scenes import FACING_TARGETS, inject_orientation_defects


def sample_scene():
    positions = {
        "desk_01": [2.0, 0.0, 3.0],
        "chair_01": [2.0, 0.0, 1.5],
        "monitor_01": [2.0, 0.7, 2.8],
        "laptop_01": [1.5, 0.7, 2.7],
    }
    return {
        "scene_id": "test",
        "assets_dir": "assets",
        "objects": [
            {
                "id": object_id,
                "asset": f"{object_id.removesuffix('_01')}_v1.glb",
                "position": position,
                "rotation_y_deg": 0.0,
            }
            for object_id, position in positions.items()
        ],
    }


class OrientationEvalSceneTests(unittest.TestCase):
    def test_injects_exactly_four_verified_orientation_violations(self):
        scene = sample_scene()
        offsets = {obj["asset"]: 0.0 for obj in scene["objects"]}

        result = inject_orientation_defects(scene, offsets, 135.0)
        violations = mc.check_semantic_constraints(result, offsets)
        orientation = [v for v in violations if v["type"] == "orientation"]

        self.assertEqual(4, len(orientation))
        self.assertEqual(set(FACING_TARGETS),
                         {v["object_id"] for v in orientation})
        self.assertTrue(all(abs(abs(v["angle_error_deg"]) - 135.0) < 1e-6
                            for v in orientation))
        self.assertFalse(any(v["type"] == "orientation_unverified"
                             for v in violations))
        self.assertEqual(4, result["evaluation_injection"]["expected_positive_count"])

    def test_does_not_modify_source_scene(self):
        scene = sample_scene()
        offsets = {obj["asset"]: 0.0 for obj in scene["objects"]}
        inject_orientation_defects(scene, offsets, 90.0)
        self.assertTrue(all("faces" not in obj for obj in scene["objects"]))

    def test_rejects_unresolved_front_offset(self):
        scene = sample_scene()
        offsets = {obj["asset"]: 0.0 for obj in scene["objects"]}
        offsets["laptop_v1.glb"] = None
        with self.assertRaisesRegex(ValueError, "front_offset_deg"):
            inject_orientation_defects(scene, offsets, 90.0)


if __name__ == "__main__":
    unittest.main()
