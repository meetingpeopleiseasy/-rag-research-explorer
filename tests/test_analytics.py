import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import analytics_service  # noqa: E402


def _make_db(tmpdir, rows):
    db = os.path.join(tmpdir, "papers.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE papers (paper_id TEXT PRIMARY KEY, title TEXT, abstract TEXT, "
        "year INTEGER, authors_json TEXT)"
    )
    for paper_id, title, abstract, year, authors in rows:
        conn.execute(
            "INSERT INTO papers (paper_id, title, abstract, year, authors_json) VALUES (?, ?, ?, ?, ?)",
            (paper_id, title, abstract, year, json.dumps(authors)),
        )
    conn.commit()
    conn.close()
    return db


class TestAnalytics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = _make_db(
            cls.tmp.name,
            [
                ("W1", "Retrieval-Augmented Generation for QA", "evaluation of retrieval augmented generation", 2021, ["Alice"]),
                ("W2", "Multimodal RAG", "multimodal retrieval systems", 2024, ["Bob"]),
                ("W3", "RAG systems", "retrieval augmented systems evaluation", 2025, ["Alice"]),
                ("W4", "Multimodal QA", "multimodal question answering", 2025, ["Carol"]),
                ("W5", "Unrelated", "however such results", 2025, ["unknown", "University of X"]),
            ],
        )
        cls.papers = analytics_service._load_papers(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_publication_trend_counts(self):
        trend = analytics_service.publication_trend(self.papers)
        self.assertEqual(sum(trend["counts"]), 5)

    def test_top_authors_normalized(self):
        authors = analytics_service.top_authors(self.papers)
        names = [item["author"] for item in authors["authors"]]
        self.assertIn("Alice", names)
        self.assertNotIn("unknown", names)
        self.assertFalse(any("University" in name for name in names))

    def test_author_normalization_handles_last_first_and_case(self):
        self.assertEqual(analytics_service._normalize_author("DOE, JANE"), "Jane Doe")
        self.assertIsNone(analytics_service._normalize_author("unknown"))
        self.assertIsNone(analytics_service._normalize_author("University of X"))

    def test_emerging_keywords_flags_new_and_small_base(self):
        emerging = analytics_service.emerging_keywords(
            self.papers, early_start=2021, early_end=2021, late_start=2024, late_end=2025
        )
        by_term = {item["term"]: item for item in emerging["keywords"]}
        self.assertIn("multimodal", by_term)
        self.assertTrue(by_term["multimodal"]["new"])
        self.assertTrue(by_term["multimodal"]["small_base"])
        self.assertEqual(emerging["incomplete_year"], "2026")

    def test_topics_are_phrases_not_stopwords(self):
        topics = analytics_service._extract_topics(self.papers, limit=8)
        self.assertTrue(topics)
        self.assertFalse(any(topic["term"].lower() in {"however", "such", "results"} for topic in topics))

    def test_scope_filters_status(self):
        screened_path = os.path.join(self.tmp.name, "screened.json")
        with open(screened_path, "w", encoding="utf-8") as fh:
            json.dump(
                {"papers": [
                    {"paperId": "W1", "relevance_status": "included", "doc_type": "conference_paper"},
                    {"paperId": "W2", "relevance_status": "uncertain", "doc_type": "preprint"},
                ]},
                fh,
            )
        screened = analytics_service._load_screened(screened_path)
        included = analytics_service._filter_papers(self.papers, screened, ["included"])
        uncertain = analytics_service._filter_papers(self.papers, screened, ["uncertain"])
        self.assertEqual([p["paper_id"] for p in included], ["W1"])
        self.assertEqual([p["paper_id"] for p in uncertain], ["W2"])


class TestMapData(unittest.TestCase):
    def test_map_data_builds_real_edges(self):
        fake = {
            "seed_paper": {"paper_id": "S1", "title": "Seed RAG", "abstract": "retrieval systems"},
            "related_papers": [
                {"paper_id": "R1", "title": "Related RAG", "abstract": "retrieval systems", "combined_score": 0.4}
            ],
        }
        with mock.patch.object(analytics_service.recommendation_service, "related_papers", return_value=fake):
            data = analytics_service.map_data("db", "corpus", "screened", "S1")
        self.assertTrue(any(link["relation"] == "similarity" for link in data["links"]))
        self.assertTrue(any(link["relation"] == "paper_topic" for link in data["links"]))


if __name__ == "__main__":
    unittest.main()
