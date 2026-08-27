#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from orchestrator import (
    BestState, find_repeated_repairs, has_budget_to_evaluate_repair,
    retry_after_cycle, scene_state_key)


class BestStateTests(unittest.TestCase):
    def test_keeps_first_state_on_equal_violation_count(self):
        best = BestState()
        self.assertTrue(best.consider({"value": "first"}, 0, 5))
        self.assertFalse(best.consider({"value": "equal"}, 1, 5))
        self.assertEqual(best.scene["value"], "first")
        self.assertEqual(best.iteration, 0)
        self.assertEqual(best.violation_count, 5)

    def test_updates_only_when_violation_count_decreases(self):
        best = BestState()
        best.consider({"value": "initial"}, 0, 5, 1.0)
        self.assertFalse(best.consider({"value": "worse"}, 1, 7, 0.1))
        self.assertTrue(best.consider({"value": "better"}, 2, 2, 9.0))
        self.assertEqual(best.scene["value"], "better")
        self.assertEqual(best.iteration, 2)
        self.assertEqual(best.violation_count, 2)

    def test_equal_violations_update_only_for_lower_aspect_error(self):
        best = BestState()
        best.consider({"value": "first"}, 2, 2, 8.0)
        self.assertFalse(best.consider({"value": "worse-shape"}, 3, 2, 9.0))
        self.assertFalse(best.consider({"value": "exact-tie"}, 4, 2, 8.0))
        self.assertTrue(best.consider({"value": "better-shape"}, 6, 2, 6.0))
        self.assertEqual(best.scene["value"], "better-shape")
        self.assertEqual(best.iteration, 6)
        self.assertEqual(best.aspect_ratio_error_sum, 6.0)

    def test_missing_aspect_data_keeps_first_on_equal_violations(self):
        best = BestState()
        best.consider({"value": "first"}, 0, 2)
        self.assertFalse(best.consider({"value": "second"}, 1, 2))
        self.assertEqual(best.scene["value"], "first")

    def test_stores_deep_copy(self):
        scene = {"objects": [{"position": [1, 2, 3]}]}
        best = BestState()
        best.consider(scene, 0, 1)
        scene["objects"][0]["position"][0] = 99
        self.assertEqual(best.scene["objects"][0]["position"], [1, 2, 3])

    def test_summary_records_selection_rule(self):
        best = BestState()
        best.consider({"value": "best"}, 3, 0)
        self.assertEqual(best.summary(), {
            "selection_rule": (
                "lexicographic_minimum_machine_violations_then_aspect_ratio_error"),
            "iteration": 3,
            "violation_count": 0,
            "aspect_ratio_error_sum": None,
        })


class IterationBudgetTests(unittest.TestCase):
    def test_repairs_are_allowed_only_when_a_next_evaluation_exists(self):
        self.assertTrue(has_budget_to_evaluate_repair(5, 7))
        self.assertFalse(has_budget_to_evaluate_repair(6, 7))


class RepeatedRepairTests(unittest.TestCase):
    def test_returns_only_previously_seen_messages_in_input_order(self):
        applied = ["plantを移動", "lampを移動", "bookshelfを移動"]
        seen = {"bookshelfを移動", "plantを移動"}
        self.assertEqual(
            find_repeated_repairs(applied, seen),
            ["plantを移動", "bookshelfを移動"])

    def test_returns_empty_list_when_nothing_repeats(self):
        self.assertEqual(
            find_repeated_repairs(["plantを移動"], {"lampを移動"}),
            [])

    def test_does_not_modify_inputs(self):
        applied = ["plantを移動"]
        seen = {"plantを移動"}
        find_repeated_repairs(applied, seen)
        self.assertEqual(applied, ["plantを移動"])
        self.assertEqual(seen, {"plantを移動"})


class SceneStateCycleTests(unittest.TestCase):
    def scene(self, position=None, asset="plant_v1.glb"):
        return {
            "history": [{"ignored": True}],
            "objects": [{
                "id": "plant_01",
                "asset": asset,
                "position": position or [1.0, 0.0, 2.0],
                "rotation_y_deg": 0,
                "target_dimensions": {
                    "width": 0.4, "height": 1.1, "depth": 0.4},
                "_tried_variants": ["plant_v1.glb"],
            }],
        }

    def test_same_visible_state_matches_despite_internal_metadata(self):
        first = self.scene()
        returned = self.scene()
        returned["history"] = [{"different": "metadata"}]
        returned["objects"][0]["_tried_variants"].append("plant_v2.glb")
        self.assertEqual(scene_state_key(first), scene_state_key(returned))

    def test_position_change_is_a_different_state(self):
        self.assertNotEqual(
            scene_state_key(self.scene()),
            scene_state_key(self.scene(position=[1.2, 0.0, 2.0])))

    def test_variant_change_is_a_different_state(self):
        self.assertNotEqual(
            scene_state_key(self.scene()),
            scene_state_key(self.scene(asset="plant_v2.glb")))


class CycleRetryTests(unittest.TestCase):
    def scene(self):
        return {
            "room": {
                "bounds": {"width": 10.0, "depth": 10.0},
                "entrance": {"position": [0.2, 0.2]},
            },
            "objects": [
                {
                    "id": "bookshelf_01",
                    "asset": "bookshelf_v1.glb",
                    "position": [5.0, 0.0, 5.0],
                    "target_dimensions": {
                        "width": 1.0, "height": 2.0, "depth": 0.4},
                    "locked": False,
                },
                {
                    "id": "plant_01",
                    "asset": "plant_v1.glb",
                    "asset_variants": [
                        "plant_v1.glb", "plant_v2.glb", "plant_v3.glb"],
                    "position": [8.0, 0.0, 8.0],
                    "target_dimensions": {
                        "width": 0.4, "height": 1.1, "depth": 0.4},
                    "locked": False,
                },
            ],
        }

    def dimensions(self):
        return {
            "plant_v1.glb": (0.99, 1.0, 0.84),
            "plant_v2.glb": (0.63, 1.0, 0.59),
            "plant_v3.glb": (0.46, 1.0, 0.51),
        }

    def retry(self, dimensions):
        previous = self.scene()
        cycle = self.scene()
        seen = {scene_state_key(cycle): 2}
        records = [{
            "object_id": "bookshelf_01",
            "op": "push_apart",
            "message": "bookshelf_01: 無進展の移動",
        }]
        violations = [{
            "type": "walkability",
            "object_id": "bookshelf_01",
            "suggested_repair": "push_apart",
        }]
        return retry_after_cycle(
            previous, cycle, records, violations, None, "assets", [], seen,
            asset_dimensions=dimensions)

    def test_no_progress_bans_previous_repair_and_reaches_aspect_swap(self):
        result = self.retry(self.dimensions())
        plant = next(obj for obj in result["scene"]["objects"]
                     if obj["id"] == "plant_01")
        self.assertIsNone(result["stop_reason"])
        self.assertEqual(plant["asset"], "plant_v3.glb")
        self.assertIn("縦横比補正", result["applied"][0])
        self.assertEqual(result["banned_repairs"], [{
            "object_id": "bookshelf_01", "op": "push_apart"}])
        self.assertIn(
            {"object_id": "bookshelf_01", "op": "push_apart"},
            result["scene"]["_failed_repairs"])

    def test_exhausted_candidates_stop_after_cycle(self):
        result = self.retry({})
        self.assertEqual(result["applied"], [])
        self.assertEqual(
            result["stop_reason"], "exhausted_after_cycle")


if __name__ == "__main__":
    unittest.main()
