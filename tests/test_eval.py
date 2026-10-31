import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_search


class TestEvalMetrics(unittest.TestCase):
    def test_strict_and_loose_precision(self):
        results = [
            {"paper_id": "W1"}, {"paper_id": "W2"}, {"paper_id": "W3"},
            {"paper_id": "W4"}, {"paper_id": "W5"},
        ]
        annotations = {"W1": 2, "W2": 2, "W3": 1, "W4": 0, "W5": 1}
        strict, judged = eval_search.compute_precision(results, annotations, 5, lambda v: v == 2)
        loose, _ = eval_search.compute_precision(results, annotations, 5, lambda v: v >= 1)
        self.assertEqual(judged, 5)
        self.assertAlmostEqual(strict, 2 / 5)
        self.assertAlmostEqual(loose, 4 / 5)

    def test_unannotated_results_are_not_counted_as_irrelevant(self):
        results = [
            {"paper_id": "W1"}, {"paper_id": "W2"}, {"paper_id": "W3"},
            {"paper_id": "W4"}, {"paper_id": "W5"},
        ]
        annotations = {"W1": 2, "W2": 2}
        precision, judged = eval_search.compute_precision(
            results, annotations, 5, lambda v: v == 2
        )
        self.assertEqual(judged, 2)
        self.assertAlmostEqual(precision, 1.0)

    def test_precision_without_annotations_is_none(self):
        results = [{"paper_id": "W1"}, {"paper_id": "W2"}]
        precision, judged = eval_search.compute_precision(
            results, {}, 5, lambda v: v == 2
        )
        self.assertIsNone(precision)
        self.assertEqual(judged, 0)

    def test_tie_groups(self):
        results = [
            {"bm25_score": -1.0},
            {"bm25_score": -1.0},
            {"bm25_score": -2.0},
            {"bm25_score": -2.0000001},
        ]
        self.assertEqual(eval_search.count_tie_groups(results), 2)


class TestRunQuery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "eval.db")
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE papers (
                paper_id TEXT PRIMARY KEY, title TEXT, abstract TEXT, year INTEGER,
                venue TEXT, doi TEXT, cited_by_count INTEGER, normalized_title TEXT
            );
            CREATE VIRTUAL TABLE papers_fts USING fts5(paper_id UNINDEXED, title, abstract);
            """
        )
        conn.execute(
            "INSERT INTO papers (paper_id, title, abstract, year, venue, doi, cited_by_count, normalized_title) "
            "VALUES ('W1', 'Retrieval-Augmented Generation', 'RAG survey', 2024, 'venue', 'https://doi.org/10.1/x', 3, 'retrieval augmented generation')"
        )
        conn.execute(
            "INSERT INTO papers_fts (paper_id, title, abstract) VALUES ('W1', 'Retrieval-Augmented Generation', 'RAG survey')"
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_query_returns_paper_id(self):
        results = eval_search.run_query(self.db_path, "RAG", k=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["paper_id"], "W1")


if __name__ == "__main__":
    unittest.main()
