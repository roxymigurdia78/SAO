import contextlib
import io
import unittest

import make_fig1


class MakeFig1BestSummaryTests(unittest.TestCase):
    def make_record(self, with_best_summary):
        best_summary = None
        if with_best_summary:
            best_summary = {
                "selection_rule": (
                    "lexicographic_minimum_machine_violations_then_aspect_ratio_error"),
                "iteration": 1,
                "violation_count": 0,
                "aspect_ratio_error_sum": 1.25,
            }
        return {
            "dir": "study_room_seed1_20260827_120000",
            "n": [0, 1],
            "viol": [0, 0],
            "mean": [4.0, 3.0],
            "best_summary": best_summary,
        }

    def test_new_run_reports_best_state_rule_not_vlm_warning(self):
        record = self.make_record(True)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            make_fig1.summarize([record])

        text = output.getvalue()
        self.assertIn("ベスト保持: iter 1 (機械違反 0, 縦横比誤差合計 1.25)", text)
        self.assertNotIn("VLM平均スコアが最終反復で最高値を下回っている", text)

    def test_old_run_keeps_explicit_vlm_warning(self):
        record = self.make_record(False)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            make_fig1.summarize([record])

        self.assertIn(
            "VLM平均スコアが最終反復で最高値を下回っている",
            output.getvalue())


if __name__ == "__main__":
    unittest.main()
