import unittest
from pathlib import Path

import unity_bridge


class UnityCommandTests(unittest.TestCase):
    def command(self, fast, details=False, uniform=False):
        return unity_bridge.build_command(
            "Unity.exe", "Project", "scene.json", "capture", "unity.log",
            fast_iteration=fast, detail_captures=details,
            uniform_scale=uniform)

    def test_normal_mode_does_not_add_fast_flag(self):
        self.assertNotIn("-fastIteration", self.command(False))

    def test_fast_mode_adds_fast_flag_without_changing_required_arguments(self):
        command = self.command(True)
        self.assertIn("-fastIteration", command)
        self.assertEqual("MVL.BatchEntry.Run",
                         command[command.index("-executeMethod") + 1])
        self.assertEqual(str(Path("scene.json").resolve()),
                         command[command.index("-sceneJson") + 1])

    def test_detail_mode_adds_detail_capture_flag(self):
        command = self.command(False, details=True)
        self.assertIn("-detailCaptures", command)
        self.assertNotIn("-fastIteration", command)

    def test_uniform_scale_mode_adds_explicit_unity_flag(self):
        command = self.command(False, uniform=True)
        self.assertIn("-uniformScale", command)

    def test_per_axis_scale_is_the_default(self):
        self.assertNotIn("-uniformScale", self.command(False))


if __name__ == "__main__":
    unittest.main()
