import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("flask_app", ROOT / "app.py")
flask_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flask_app)

from services import recommendation_service  # noqa: E402


def _make_db(tmpdir, rows, corpus_groups, screened):
    db_path = os.path.join(tmpdir, "papers.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE papers (paper_id TEXT PRIMARY KEY, title TEXT, abstract TEXT, "
        "year INTEGER, venue TEXT, doi TEXT, cited_by_count INTEGER, authors_json TEXT)"
    )
    for paper_id, title, abstract, authors in rows:
        conn.execute(
            "INSERT INTO papers (paper_id, title, abstract, year, venue, doi, cited_by_count, authors_json) "
            "VALUES (?, ?, ?, 2024, 'venue', ?, 0, ?)",
            (paper_id, title, abstract, paper_id, json.dumps(authors)),
        )
    conn.commit()
    conn.close()

    corpus_path = os.path.join(tmpdir, "corpus.json")
    with open(corpus_path, "w", encoding="utf-8") as fh:
        json.dump({"version_groups": corpus_groups, "different_work_groups": []}, fh)

    screened_path = os.path.join(tmpdir, "screened.json")
    with open(screened_path, "w", encoding="utf-8") as fh:
        json.dump({"papers": screened}, fh)
    return db_path, corpus_path, screened_path


class TestRecommendation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        rows = [
            ("W1", "Retrieval-Augmented Generation for Question Answering", "RAG combines retrieval with generation for question answering.", ["Alice"]),
            ("W2", "Retrieval-Augmented Generation for Question Answering", "RAG combines retrieval with generation for question answering.", ["Alice"]),
            ("W3", "Retrieval-Augmented Generation for Question Answering", "A study of textile manufacturing processes.", ["Bob"]),
            ("W4", "Retrieval augmented question answering systems", "RAG combines retrieval with generation for question answering.", ["Alice"]),
            ("W5", "RAG", "music history", ["Carol"]),
            ("W6", "Retrieval systems", None, ["Dave"]),
            ("W7", "Retrieval augmented generation survey", "RAG combines retrieval with generation.", ["Alice"]),
        ]
        corpus_groups = [
            {"group_id": "v1", "classification": "confirmed_same_work", "paper_ids": ["W1", "W2"], "representative_id": "W1"}
        ]
        screened = [
            {"paperId": "W1", "relevance_status": "included", "doc_type": "conference_paper"},
            {"paperId": "W2", "relevance_status": "included", "doc_type": "conference_paper"},
            {"paperId": "W3", "relevance_status": "uncertain", "doc_type": "journal_article"},
            {"paperId": "W4", "relevance_status": "included", "doc_type": "conference_paper"},
            {"paperId": "W5", "relevance_status": "included", "doc_type": "unknown"},
            {"paperId": "W6", "relevance_status": "uncertain", "doc_type": "preprint"},
            {"paperId": "W7", "relevance_status": "excluded", "doc_type": "software_or_dataset"},
        ]
        cls.db, cls.corpus, cls.screened = _make_db(cls.tmp.name, rows, corpus_groups, screened)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _call(self, seed, **kwargs):
        return recommendation_service.related_papers(self.db, self.corpus, self.screened, seed, **kwargs)

    def test_seed_not_found(self):
        self.assertIsNone(self._call("NOPE"))

    def test_no_self_recommendation(self):
        result = self._call("W1")
        self.assertNotIn("W1", [item["paper_id"] for item in result["related_papers"]])

    def test_confirmed_version_duplicates_excluded(self):
        result = self._call("W1")
        self.assertNotIn("W2", [item["paper_id"] for item in result["related_papers"]])

    def test_different_work_not_merged(self):
        result = self._call("W1")
        self.assertIn("W3", [item["paper_id"] for item in result["related_papers"]])

    def test_included_before_uncertain(self):
        result = self._call("W1")
        statuses = [item["relevance_status"] for item in result["related_papers"]]
        self.assertTrue("included" in statuses)
        if "uncertain" in statuses:
            self.assertLessEqual(statuses.index("included"), statuses.index("uncertain"))

    def test_uncertain_marked(self):
        result = self._call("W1")
        by_id = {item["paper_id"]: item for item in result["related_papers"]}
        self.assertEqual(by_id["W6"]["relevance_status"], "uncertain")
        self.assertEqual(by_id["W6"]["abstract_similarity"], 0.0)

    def test_short_title_no_false_title_similarity(self):
        result = self._call("W1")
        by_id = {item["paper_id"]: item for item in result["related_papers"]}
        self.assertEqual(by_id["W5"]["title_similarity"], 0.0)

    def test_record_type_is_attached(self):
        result = self._call("W1")
        by_id = {item["paper_id"]: item for item in result["related_papers"]}
        self.assertEqual(by_id["W4"]["record_type"], "conference_paper")
        self.assertEqual(by_id["W6"]["record_type"], "preprint")

    def test_title_ranking_sorts_included_by_title_similarity(self):
        result = self._call("W1", ranking="title")
        included = [item for item in result["related_papers"] if item["relevance_status"] == "included"]
        scores = [item["title_similarity"] for item in included]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_stable_sorting(self):
        first = [item["paper_id"] for item in self._call("W1")["related_papers"]]
        second = [item["paper_id"] for item in self._call("W1")["related_papers"]]
        self.assertEqual(first, second)

    def test_no_abstract_seed_does_not_error(self):
        result = self._call("W6")
        self.assertIsNotNone(result)
        self.assertTrue(all(item["abstract_similarity"] == 0.0 for item in result["related_papers"]))

    def test_excluded_not_recommended_by_default(self):
        result = self._call("W1")
        self.assertNotIn("W7", [item["paper_id"] for item in result["related_papers"]])
        with_excluded = self._call("W1", include_excluded=True)
        self.assertIn("W7", [item["paper_id"] for item in with_excluded["related_papers"]])

    def test_candidate_confirmed_versions_are_folded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                ("S1", "Seed RAG paper", "RAG retrieval augmented generation.", ["Alice"]),
                ("C1", "Candidate version paper", "RAG retrieval augmented generation.", ["Alice"]),
                ("C2", "Candidate version paper", "RAG retrieval augmented generation.", ["Alice"]),
            ]
            corpus_groups = [
                {"group_id": "v2", "classification": "confirmed_same_work", "paper_ids": ["C1", "C2"], "representative_id": "C2"}
            ]
            screened = [
                {"paperId": "S1", "relevance_status": "included"},
                {"paperId": "C1", "relevance_status": "included"},
                {"paperId": "C2", "relevance_status": "included"},
            ]
            db, corpus, screened_path = _make_db(tmpdir, rows, corpus_groups, screened)
            result = recommendation_service.related_papers(db, corpus, screened_path, "S1")
            ids = [item["paper_id"] for item in result["related_papers"]]
            self.assertEqual(ids, ["C2"])


class TestRecommendationRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        rows = [
            ("S1", "Seed paper about RAG", "RAG retrieval augmented generation.", ["Alice"]),
            ("E1", "Excluded paper", "nothing relevant", ["Bob"]),
        ]
        screened = [
            {"paperId": "S1", "relevance_status": "included"},
            {"paperId": "E1", "relevance_status": "excluded"},
        ]
        db, corpus, screened_path = _make_db(cls.tmp.name, rows, [], screened)
        cls.app = flask_app.create_app()
        cls.app.config.update(TESTING=True, DB_PATH=db, CORPUS_PATH=corpus, SCREENED_PATH=screened_path)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_related_api(self):
        response = self.client.get("/api/paper/S1/related")
        self.assertEqual(response.status_code, 200)
        self.assertIn("seed_paper", response.get_json())
        self.assertEqual(response.get_json()["related_papers"], [])

    def test_related_api_missing_paper(self):
        self.assertEqual(self.client.get("/api/paper/NOPE/related").status_code, 404)

    def test_explore_page(self):
        self.assertEqual(self.client.get("/explore/S1").status_code, 200)
        self.assertEqual(self.client.get("/explore/NOPE").status_code, 404)


if __name__ == "__main__":
    unittest.main()
