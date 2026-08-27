#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

import repair


def scene_at(x, z):
    return {
        "room": {
            "bounds": {"width": 10.0, "depth": 10.0},
            "entrance": {"position": [0.2, 0.2]},
        },
        "objects": [{
            "id": "floor_lamp_01",
            "position": [x, 0.0, z],
            "target_dimensions": {"width": 0.1, "height": 1.6, "depth": 0.1},
            "locked": False,
        }],
    }


def printer_scene():
    return {
        "room": {
            "bounds": {"width": 4.0, "depth": 4.0},
            "floor_y": 0.0,
        },
        "objects": [
            {
                "id": "desk_01",
                "class": "desk",
                "asset": "desk_v1.glb",
                "position": [0.0, 0.0, 0.0],
                "target_dimensions": {
                    "width": 2.0, "height": 1.0, "depth": 1.0},
                "locked": True,
            },
            {
                "id": "printer_01",
                "class": "printer",
                "asset": "printer_v1.glb",
                "asset_variants": [
                    "printer_v1.glb", "printer_v2.glb", "printer_v3.glb"],
                "position": [0.5, 1.0, 0.5],
                "target_dimensions": {
                    "width": 0.4, "height": 0.3, "depth": 0.4},
                "rests_on": "desk_01",
                "must_touch_floor": False,
                "locked": False,
            },
        ],
    }


class VisualRepairTests(unittest.TestCase):
    def test_resolves_parenthesized_object_id(self):
        scene = printer_scene()
        self.assertEqual(
            repair.resolve_object_id(scene, {"id": "printer_01(printer)"}),
            "printer_01")

    def test_resolves_wrong_id_from_unique_class_in_description(self):
        scene = printer_scene()
        defect = {
            "kind": "floating",
            "description": "machine_01 (printer) is suspended in mid-air "
                           "without legs or a desk.",
        }
        self.assertEqual(
            repair.resolve_object_id(scene, defect),
            "printer_01")

    def test_visual_floating_with_numeric_contact_swaps_variant(self):
        scene = printer_scene()
        defect = {
            "kind": "floating",
            "description": "machine_01 (printer) is suspended in mid-air "
                           "without legs or a desk.",
        }
        new, applied = repair.apply_repairs(
            scene, [], visual_defects=[defect])
        printer = next(o for o in new["objects"] if o["id"] == "printer_01")
        self.assertEqual(printer["asset"], "printer_v2.glb")
        self.assertIn("VLM浮遊指摘・数値上接地済み", applied[0])

    def test_reposition_on_desk_is_supported_for_resolved_id(self):
        scene = printer_scene()
        worst = {
            "id": "printer_01(printer)",
            "suggested_repair": "reposition_on_desk",
        }
        new, applied = repair.apply_repairs(
            scene, [], worst_object=worst)
        printer = next(o for o in new["objects"] if o["id"] == "printer_01")
        self.assertEqual(printer["asset"], "printer_v2.glb")
        self.assertTrue(applied)


class PenetrationTests(unittest.TestCase):
    def test_detects_penetration_involving_requested_object(self):
        scene = scene_at(1.0, 1.0)
        scene["objects"].append({
            "id": "cabinet_01",
            "position": [1.0, 0.0, 1.0],
            "target_dimensions": {"width": 1.0, "height": 1.0, "depth": 1.0},
            "locked": True,
        })
        self.assertTrue(repair.has_penetration(scene, "floor_lamp_01"))

    def test_ignores_penetration_between_other_objects(self):
        scene = scene_at(5.0, 5.0)
        for oid in ("cabinet_01", "bookshelf_01"):
            scene["objects"].append({
                "id": oid,
                "position": [1.0, 0.0, 1.0],
                "target_dimensions": {"width": 1.0, "height": 1.0, "depth": 1.0},
                "locked": True,
            })
        self.assertFalse(repair.has_penetration(scene, "floor_lamp_01"))


class AspectRatioVariantTests(unittest.TestCase):
    def setUp(self):
        self.scene = scene_at(1.0, 1.0)
        obj = self.scene["objects"][0]
        obj.update({
            "asset": "floor_lamp_v1.glb",
            "asset_variants": [
                "floor_lamp_v1.glb", "floor_lamp_v2.glb",
                "floor_lamp_v3.glb"],
        })

    def test_swaps_to_variant_with_clearly_better_shape(self):
        dimensions = {
            "floor_lamp_v1.glb": (0.8, 1.0, 0.8),
            "floor_lamp_v2.glb": (0.2, 1.0, 0.2),
            "floor_lamp_v3.glb": (0.6, 1.0, 0.6),
        }
        new, applied = repair.apply_repairs(
            self.scene, [], asset_dimensions=dimensions)
        self.assertEqual(
            new["objects"][0]["asset"], "floor_lamp_v2.glb")
        self.assertIn("縦横比補正", applied[0])

    def test_does_not_swap_for_only_small_improvement(self):
        dimensions = {
            "floor_lamp_v1.glb": (0.24, 1.0, 0.24),
            "floor_lamp_v2.glb": (0.22, 1.0, 0.22),
            "floor_lamp_v3.glb": (0.23, 1.0, 0.23),
        }
        new, applied = repair.apply_repairs(
            self.scene, [], asset_dimensions=dimensions)
        self.assertEqual(
            new["objects"][0]["asset"], "floor_lamp_v1.glb")
        self.assertEqual(applied, [])

    def test_total_error_decreases_after_better_variant(self):
        dimensions = {
            "floor_lamp_v1.glb": (0.8, 1.0, 0.8),
            "floor_lamp_v2.glb": (0.2, 1.0, 0.2),
            "floor_lamp_v3.glb": (0.6, 1.0, 0.6),
        }
        before = repair.total_aspect_ratio_error(self.scene, dimensions)
        new, _ = repair.apply_repairs(
            self.scene, [], asset_dimensions=dimensions)
        after = repair.total_aspect_ratio_error(new, dimensions)
        self.assertLess(after, before)


class FailedRepairKeyTests(unittest.TestCase):
    def test_same_object_allows_a_different_operator(self):
        scene = scene_at(1.0, 1.0)
        obj = scene["objects"][0]
        obj["class_height_range"] = [1.0, 2.0]
        obj["target_dimensions"]["height"] = 3.0
        scene["_failed_repairs"] = [{
            "object_id": "floor_lamp_01", "op": "push_apart"}]
        violation = {
            "type": "scale",
            "object_id": "floor_lamp_01",
            "suggested_repair": "rescale",
        }
        new, applied, records = repair.apply_repairs(
            scene, [violation], asset_dimensions={}, return_records=True)
        self.assertTrue(applied)
        self.assertEqual(new["objects"][0]["target_dimensions"]["height"], 1.5)
        self.assertEqual(records[0]["op"], "rescale")

    def test_objectless_walkability_records_actual_moved_id(self):
        scene = scene_at(1.0, 1.0)
        violation = {
            "type": "walkability",
            "suggested_repair": "push_apart",
        }
        message = "floor_lamp_01: [1.0,1.0]→[2.0,2.0](動線確保のため移動)"
        with patch("repair.relocate_blocker", return_value=message):
            new, applied, records = repair.apply_repairs(
                scene, [violation], asset_dimensions={}, return_records=True)
        self.assertEqual(applied, [message])
        self.assertEqual(records, [{
            "object_id": "floor_lamp_01",
            "op": "push_apart",
            "message": message,
        }])
        repair.add_failed_repairs(new, records)
        self.assertTrue(repair.is_repair_failed(
            new, "floor_lamp_01", "push_apart"))

    def test_old_string_failure_format_is_backward_compatible(self):
        scene = scene_at(1.0, 1.0)
        scene["objects"][0]["class_height_range"] = [1.0, 2.0]
        scene["_failed_repairs"] = [
            "floor_lamp_01: [1.0,1.0]→[2.0,2.0](旧ログ)"]
        violation = {
            "type": "scale",
            "object_id": "floor_lamp_01",
            "suggested_repair": "rescale",
        }
        _, applied = repair.apply_repairs(
            scene, [violation], asset_dimensions={})
        self.assertEqual(applied, [])

    def test_does_not_retry_a_variant_after_rollback(self):
        scene = scene_at(1.0, 1.0)
        scene["objects"][0].update({
            "asset": "floor_lamp_v1.glb",
            "asset_variants": [
                "floor_lamp_v1.glb", "floor_lamp_v2.glb",
                "floor_lamp_v3.glb"],
        })
        scene["objects"][0]["_tried_variants"] = [
            "floor_lamp_v1.glb", "floor_lamp_v2.glb"]
        dimensions = {
            "floor_lamp_v1.glb": (0.8, 1.0, 0.8),
            "floor_lamp_v2.glb": (0.2, 1.0, 0.2),
            "floor_lamp_v3.glb": (0.7, 1.0, 0.7),
        }
        new, applied = repair.apply_repairs(
            scene, [], asset_dimensions=dimensions)
        self.assertEqual(
            new["objects"][0]["asset"], "floor_lamp_v1.glb")
        self.assertEqual(applied, [])


class RelocateBlockerTests(unittest.TestCase):
    @patch("repair._clamp_obj")
    @patch("repair.mc.walkability_grid", return_value=([[True]], 7.0, 1, 1))
    @patch("repair.mc.collect_aabbs", return_value={})
    def test_same_destination_is_not_counted_as_repair(
            self, _collect, _grid, _clamp):
        scene = scene_at(3.5, 3.5)
        result = repair.relocate_blocker(
            scene, {"object_id": "floor_lamp_01"})
        self.assertIsNone(result)
        self.assertEqual(scene["objects"][0]["position"], [3.5, 0.0, 3.5])

    @patch("repair._clamp_obj")
    @patch("repair.mc.walkability_grid", return_value=([[True]], 7.0, 1, 1))
    @patch("repair.mc.collect_aabbs", return_value={})
    def test_real_move_returns_repair_message(
            self, _collect, _grid, _clamp):
        scene = scene_at(1.0, 1.0)
        result = repair.relocate_blocker(
            scene, {"object_id": "floor_lamp_01"})
        self.assertIn("[1.0,1.0]→[3.5,3.5]", result)
        self.assertEqual(scene["objects"][0]["position"], [3.5, 0.0, 3.5])

    @patch("repair.mc.walkability_grid",
           return_value=([[True], [True], [True]], 2.0, 3, 1))
    def test_skips_farthest_candidate_when_it_would_penetrate(self, _grid):
        scene = scene_at(1.0, 1.0)
        scene["room"]["bounds"] = {"width": 6.0, "depth": 3.0}
        scene["objects"].append({
            "id": "cabinet_01",
            "position": [5.0, 0.0, 1.0],
            "target_dimensions": {"width": 1.0, "height": 1.0, "depth": 1.0},
            "locked": True,
        })
        result = repair.relocate_blocker(
            scene, {"object_id": "floor_lamp_01"})
        self.assertIn("[1.0,1.0]→[3.0,1.0]", result)
        self.assertEqual(scene["objects"][0]["position"], [3.0, 0.0, 1.0])


if __name__ == "__main__":
    unittest.main()
