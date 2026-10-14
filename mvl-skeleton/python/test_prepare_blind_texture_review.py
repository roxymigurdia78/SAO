import csv
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from prepare_blind_texture_review import prepare_blind_review


class BlindTextureReviewTests(unittest.TestCase):
    def workspace_temp_dir(self):
        return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)

    def test_outputs_blind_samples_answers_and_separate_mapping(self):
        with self.workspace_temp_dir() as directory:
            root = Path(directory)
            source_dir = root / "source"
            source_dir.mkdir()
            for index, color in enumerate(("red", "green", "blue"), 1):
                Image.new("RGB", (16, 16), color).save(
                    source_dir / f"wall_{index:02d}.png")

            output_dir = root / "review"
            result = prepare_blind_review(
                source_dir, output_dir, seed=7, per_sheet=2)

            self.assertEqual(3, result["count"])
            self.assertEqual(
                ["B001.png", "B002.png", "B003.png"],
                sorted(path.name for path in (output_dir / "samples").glob("*.png")))
            self.assertEqual(2, len(result["sheets"]))

            with (output_dir / "visual_labels.csv").open(
                    encoding="utf-8-sig", newline="") as stream:
                answers = list(csv.DictReader(stream))
            self.assertEqual(["B001", "B002", "B003"],
                             [row["blind_id"] for row in answers])
            self.assertTrue(all(not row["visual_label"] for row in answers))
            self.assertTrue(all("source_file" not in row for row in answers))

            with (output_dir / "mapping_DO_NOT_OPEN.csv").open(
                    encoding="utf-8-sig", newline="") as stream:
                mapping = list(csv.DictReader(stream))
            self.assertEqual(3, len(mapping))
            self.assertTrue(all(row["source_file"].startswith("wall_")
                                for row in mapping))


if __name__ == "__main__":
    unittest.main()
