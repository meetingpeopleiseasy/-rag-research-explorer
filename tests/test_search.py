import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import search_papers


SCHEMA = """
CREATE TABLE papers (
    paper_id TEXT PRIMARY KEY,
    title TEXT,
    abstract TEXT,
    year INTEGER,
    venue TEXT,
    doi TEXT,
    cited_by_count INTEGER,
    normalized_title TEXT
);
CREATE VIRTUAL TABLE papers_fts USING fts5(
    paper_id UNINDEXED,
    title,
    abstract
);
"""


def make_db(rows):
    tmp = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmp.name, "search.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    for paper_id, title, abstract in rows:
        conn.execute(
            "INSERT INTO papers (paper_id, title, abstract, year, venue, doi, cited_by_count) "
            "VALUES (?, ?, ?, 2024, 'venue', NULL, 0)",
            (paper_id, title, abstract),
        )
        conn.execute(
            "INSERT INTO papers_fts (paper_id, title, abstract) VALUES (?, ?, ?)",
            (paper_id, title, abstract),
        )
    conn.commit()
    conn.close()
    return tmp, db_path


class TestBuildFtsQuery(unittest.TestCase):
    def test_normal_hyphen(self):
        self.assertEqual(search_papers.build_fts_query("retrieval-augmented"), "retrieval augmented")

    def test_normal_colon_and_parentheses(self):
        self.assertEqual(
            search_papers.build_fts_query("RAG evaluation: (survey)"),
            "RAG evaluation survey",
        )

    def test_normal_quotes(self):
        self.assertEqual(search_papers.build_fts_query('"retrieval augmented"'), "retrieval augmented")

    def test_advanced_preserves_phrase_and_prefix(self):
        self.assertEqual(search_papers.build_fts_query('"retrieval augmented"', advanced=True), '"retrieval augmented"')
        self.assertEqual(search_papers.build_fts_query("RAG*", advanced=True), "RAG*")

    def test_empty_and_whitespace_input(self):
        for text in ("", "   ", "\n\t"):
            with self.assertRaises(ValueError):
                search_papers.build_fts_query(text)
            with self.assertRaises(ValueError):
                search_papers.build_fts_query(text, advanced=True)


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.tmp, self.db_path = make_db(
            [
                ("W1", "Retrieval-Augmented Generation", "A survey of retrieval augmented generation."),
                ("W2", "RAG evaluation", "Evaluation methods for RAG."),
                ("W3", "Graph neural networks", "Unrelated topic with no match here."),
            ]
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal_hyphen_query_returns_results(self):
        rows = search_papers.search(self.db_path, "retrieval-augmented", 10)
        self.assertGreater(len(rows), 0)

    def test_normal_colon_and_paren_query_does_not_error(self):
        rows = search_papers.search(self.db_path, "evaluation: (RAG)", 10)
        self.assertGreater(len(rows), 0)

    def test_advanced_phrase_query(self):
        rows = search_papers.search(self.db_path, '"retrieval augmented"', 10, advanced=True)
        self.assertGreater(len(rows), 0)

    def test_advanced_prefix_query(self):
        rows = search_papers.search(self.db_path, "retriev*", 10, advanced=True)
        self.assertGreater(len(rows), 0)

    def test_invalid_advanced_query_raises_clear_error(self):
        with self.assertRaises(ValueError) as ctx:
            search_papers.search(self.db_path, "retrieval-augmented", 10, advanced=True)
        self.assertIn("FTS5 查询语法错误", str(ctx.exception))

    def test_no_result_query(self):
        rows = search_papers.search(self.db_path, "zzz-no-such-term", 10)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
