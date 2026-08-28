import unittest
from unittest.mock import patch

import machine_checks as mc


def semantic_scene():
    return {
        "room": {
            "bounds": {"width": 6.0, "depth": 6.0, "height": 3.0},
            "floor_y": 0.0,
            "entrance": {"position": [0.2, 0.2]},
        },
        "spec": {"required_objects": []},
        "objects": [
            {
                "id": "chair_01", "class": "chair", "asset": "chair_v1.glb",
                "position": [1.0, 0.0, 1.0], "rotation_y_deg": 180.0,
                "target_dimensions": {"width": 0.5, "height": 0.9, "depth": 0.5},
                "faces": "desk_01",
                "near": {"target": "desk_01", "max_distance": 1.0},
            },
            {
                "id": "desk_01", "class": "desk", "asset": "desk_v1.glb",
                "position": [1.0, 0.0, 3.0], "rotation_y_deg": 0.0,
                "target_dimensions": {"width": 1.2, "height": 0.7, "depth": 0.6},
            },
        ],
    }


class WalkabilityAggregationTests(unittest.TestCase):
    @patch("machine_checks.walkability_grid")
    def test_unreachable_desk_does_not_add_six_desktop_violations(self, grid):
        cells = [[False] * 10 for _ in range(10)]
        cells[0][0] = True
        grid.return_value = (cells, 1.0, 10, 10)
        required = [{"class": "desk"}]
        objects = [{
            "id": "desk_01", "class": "desk", "position": [8.0, 0.0, 8.0],
            "rotation_y_deg": 0,
            "target_dimensions": {"width": 1.2, "height": 0.7, "depth": 0.6},
        }]
        for index in range(6):
            cls = f"desktop_{index}"
            required.append({"class": cls})
            objects.append({
                "id": f"desktop_{index}", "class": cls,
                "position": [8.0, 0.7, 8.0], "rotation_y_deg": 0,
                "target_dimensions": {"width": 0.1, "height": 0.1, "depth": 0.1},
                "rests_on": "desk_01",
            })
        scene = {
            "room": {
                "bounds": {"width": 10.0, "depth": 10.0, "height": 3.0},
                "entrance": {"position": [0.2, 0.2]},
            },
            "spec": {"required_objects": required},
            "objects": objects,
        }

        violations = mc.check_walkability(scene, mc.collect_aabbs(scene))
        unreachable = [v for v in violations if v.get("object_id")]

        self.assertEqual(1, len(unreachable))
        self.assertEqual("desk_01", unreachable[0]["object_id"])
        self.assertEqual(7, len(unreachable[0]["included_object_ids"]))

    @patch("machine_checks.walkability_grid")
    def test_reach_ratio_counts_only_entrance_connected_free_cells(self, grid):
        grid.return_value = ([[True, False], [False, True]], 1.0, 2, 2)
        scene = {
            "room": {"bounds": {"width": 2, "depth": 2},
                     "entrance": {"position": [0.1, 0.1]}},
            "objects": [],
        }
        self.assertEqual(0.5, mc.walkability_reach_ratio(scene, {}))


class SemanticConstraintTests(unittest.TestCase):
    def test_orientation_and_distance_are_detected(self):
        violations = mc.check_semantic_constraints(semantic_scene(), {})
        self.assertEqual(["orientation", "too_far"],
                         [v["type"] for v in violations])

    def test_front_offset_from_inventory_changes_effective_front(self):
        scene = semantic_scene()
        scene["objects"][0]["near"]["max_distance"] = 3.0
        violations = mc.check_semantic_constraints(
            scene, {"chair_v1.glb": 180.0})
        self.assertEqual([], violations)

    def test_explicitly_unresolved_front_is_not_assumed_to_be_zero(self):
        scene = semantic_scene()
        scene["objects"][0]["near"]["max_distance"] = 3.0
        violations = mc.check_semantic_constraints(
            scene, {"chair_v1.glb": None})
        self.assertEqual(["orientation_unverified"],
                         [v["type"] for v in violations])

    def test_no_declared_constraints_preserves_old_behavior(self):
        scene = semantic_scene()
        scene["objects"][0].pop("faces")
        scene["objects"][0].pop("near")
        self.assertEqual([], mc.check_semantic_constraints(scene, {}))


if __name__ == "__main__":
    unittest.main()
