#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from orchestrator import BestState


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
        best.consider({"value": "initial"}, 0, 5)
        self.assertFalse(best.consider({"value": "worse"}, 1, 7))
        self.assertTrue(best.consider({"value": "better"}, 2, 2))
        self.assertEqual(best.scene["value"], "better")
        self.assertEqual(best.iteration, 2)
        self.assertEqual(best.violation_count, 2)

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
            "selection_rule": "minimum_machine_violation_count",
            "iteration": 3,
            "violation_count": 0,
        })


if __name__ == "__main__":
    unittest.main()
