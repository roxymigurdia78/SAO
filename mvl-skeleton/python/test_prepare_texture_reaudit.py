#!/usr/bin/env python3
import unittest

from prepare_texture_reaudit import build_html


class PrepareTextureReauditTests(unittest.TestCase):
    def test_html_contains_each_blind_image_and_two_independent_axes(self):
        html = build_html(["B001", "B002"])
        self.assertIn('samples/B001.png', html)
        self.assertIn('samples/B002.png', html)
        self.assertIn('name="B001_seam"', html)
        self.assertIn('name="B001_repeat"', html)
        self.assertIn('human_labels_v2.csv', html)
        self.assertNotIn('visual_label', html)


if __name__ == "__main__":
    unittest.main()
