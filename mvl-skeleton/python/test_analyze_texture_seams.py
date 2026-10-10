import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from analyze_texture_seams import analyze_directory, seam_metrics


class TextureSeamTests(unittest.TestCase):
    def workspace_temp_dir(self):
        return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)

    def make_periodic_texture(self, path: Path, broken: bool = False) -> None:
        y, x = np.mgrid[:64, :64]
        brick = (((x // 8) + ((y // 8) % 2) * 4) % 16 < 14)
        mortar = (y % 8) < 1
        values = np.where(brick & ~mortar, 170, 55).astype(np.uint8)
        rgb = np.repeat(values[:, :, None], 3, axis=2)
        if broken:
            rgb[:, 0, :] = 255 - rgb[:, -1, :]
        Image.fromarray(rgb, "RGB").save(path)

    def test_broken_boundary_scores_higher_than_periodic_boundary(self):
        with self.workspace_temp_dir() as directory:
            root = Path(directory)
            good = root / "good.png"
            bad = root / "bad.png"
            self.make_periodic_texture(good)
            self.make_periodic_texture(bad, broken=True)

            good_score = seam_metrics(good)["lr_edge_ratio"]
            bad_score = seam_metrics(bad)["lr_edge_ratio"]
            self.assertGreater(bad_score, good_score)

    def test_directory_writes_csv_and_2x2_preview(self):
        with self.workspace_temp_dir() as directory:
            root = Path(directory)
            source = root / "brick.png"
            self.make_periodic_texture(source)
            output = root / "metrics.csv"
            previews = root / "previews"

            rows = analyze_directory(root, output, previews)

            self.assertEqual(1, len(rows))
            self.assertTrue(output.is_file())
            self.assertTrue((root / "seam_review.png").is_file())
            preview = Image.open(previews / "brick_2x2.png")
            self.assertEqual((128, 128), preview.size)
            preview.close()


if __name__ == "__main__":
    unittest.main()
