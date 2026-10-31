import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import eval_recommendation  # noqa: E402


class TestRecommendationMetrics(unittest.TestCase):
    def test_precision_strict_and_loose(self):
        results = [
            {"paper_id": "W1"}, {"paper_id": "W2"}, {"paper_id": "W3"},
            {"paper_id": "W4"}, {"paper_id": "W5"},
        ]
        annotations = {"W1": 2, "W2": 2, "W3": 1, "W4": 0, "W5": 1}
        strict, judged = eval_recommendation.precision_at_k(
            results, annotations, 5, lambda v: v == 2
        )
        loose, _ = eval_recommendation.precision_at_k(
            results, annotations, 5, lambda v: v >= 1
        )
        self.assertEqual(judged, 5)
        self.assertAlmostEqual(strict, 2 / 5)
        self.assertAlmostEqual(loose, 4 / 5)

    def test_metric_without_annotations_is_none(self):
        results = [{"paper_id": "W1"}, {"paper_id": "W2"}]
        metric = eval_recommendation.metric(results, {})
        self.assertIsNone(metric["precision_at_5_strict"])
        self.assertIsNone(metric["precision_at_10_loose"])
        self.assertEqual(metric["judged_at_5"], 0)


if __name__ == "__main__":
    unittest.main()
