import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_db
import corpus


def record(**kwargs):
    base = {
        "paperId": None,
        "title": None,
        "abstract": None,
        "year": None,
        "publicationDate": None,
        "doi": None,
        "venue": None,
        "type": None,
        "language": None,
        "citedByCount": None,
        "authors": [],
        "biblio": None,
        "source": "openalex",
        "externalIds": {},
        "matched_queries": [],
        "matched_years": [],
        "run_id": None,
    }
    base.update(kwargs)
    return base


class TestMerge(unittest.TestCase):
    def test_doi_duplicate_merges(self):
        a = record(
            paperId="W1", doi="https://doi.org/10.1/x", title="RAG survey",
            year=2023, authors=["A"], venue="v",
            matched_queries=["q1"], matched_years=["2023"], run_id="r1",
        )
        b = record(
            paperId="W2", doi="https://doi.org/10.1/X", title="RAG survey",
            year=2023, authors=["A"], venue="v",
            matched_queries=["q2"], matched_years=["2024"], run_id="r2",
        )
        result = corpus.merge_records([a, b])
        self.assertEqual(len(result["papers"]), 1)
        self.assertEqual(result["papers"][0]["dedup_status"], "merged_by_doi")
        self.assertEqual(sorted(result["papers"][0]["matched_queries"]), ["q1", "q2"])
        self.assertEqual(sorted(result["papers"][0]["matched_years"]), ["2023", "2024"])
        self.assertEqual(result["papers"][0]["openalex_ids"], ["W1", "W2"])
        self.assertEqual(result["conflicts"], [])

    def test_no_doi_title_duplicate_merges(self):
        a = record(
            paperId="W1", title="RAG survey", year=2023, authors=["A"], venue="v",
            matched_queries=["q1"],
        )
        b = record(
            paperId="W2", title="  RAG Survey ", year=2023, authors=["A"], venue="v",
            matched_queries=["q2"],
        )
        result = corpus.merge_records([a, b])
        self.assertEqual(len(result["papers"]), 1)
        self.assertEqual(result["papers"][0]["dedup_status"], "merged_by_title")

    def test_title_conflict_keeps_both_and_records_conflict(self):
        a = record(paperId="W1", title="RAG survey", year=2023, authors=["A"], venue="v")
        b = record(paperId="W2", title="RAG survey", year=2024, authors=["A"], venue="v")
        result = corpus.merge_records([a, b])
        self.assertEqual(len(result["papers"]), 2)
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["conflicts"][0]["reason"], "same_title_conflicting_fields")

    def test_cross_year_merge_unions_years_and_runs(self):
        a = record(
            paperId="W1", doi="https://doi.org/10.1/x", title="T", year=2023, authors=["A"],
            matched_queries=["q1"], matched_years=["2023"], run_id="r1",
        )
        b = record(
            paperId="W1", doi="https://doi.org/10.1/x", title="T", year=2023, authors=["A"],
            matched_queries=["q2"], matched_years=["2024"], run_id="r2",
        )
        result = corpus.merge_records([a, b])
        self.assertEqual(len(result["papers"]), 1)
        self.assertEqual(sorted(result["papers"][0]["matched_years"]), ["2023", "2024"])
        self.assertEqual(sorted(result["papers"][0]["run_ids"]), ["r1", "r2"])

    def test_empty_abstract_fills_from_duplicate(self):
        a = record(paperId="W1", doi="https://doi.org/10.1/x", title="T", abstract=None, year=2023)
        b = record(paperId="W1", doi="https://doi.org/10.1/x", title="T", abstract="real abstract", year=2023)
        result = corpus.merge_records([a, b])
        self.assertEqual(len(result["papers"]), 1)
        self.assertEqual(result["papers"][0]["abstract"], "real abstract")

    def test_same_title_different_doi_kept_and_marked(self):
        a = record(paperId="W1", doi="https://doi.org/10.1/x", title="RAG survey", year=2023)
        b = record(paperId="W2", doi="https://doi.org/10.2/y", title="RAG survey", year=2024)
        result = corpus.merge_records([a, b])
        self.assertEqual(len(result["papers"]), 2)
        self.assertEqual(len(result["conflicts"]), 0)
        self.assertEqual(len(result["title_duplicate_groups"]), 1)
        self.assertEqual(result["title_duplicate_groups"][0]["reason"], "same_title_different_doi")

    def test_same_title_partial_doi_kept_and_marked(self):
        a = record(paperId="W1", doi="https://doi.org/10.1/x", title="RAG survey", year=2023)
        b = record(paperId="W2", doi=None, title="RAG survey", year=2023)
        result = corpus.merge_records([a, b])
        self.assertEqual(len(result["papers"]), 2)
        self.assertEqual(len(result["title_duplicate_groups"]), 1)
        self.assertEqual(result["title_duplicate_groups"][0]["reason"], "same_title_partial_doi")

    def test_merge_result_exposes_group_counts(self):
        result = corpus.merge_records(
            [
                record(paperId="W1", doi="https://doi.org/10.1/x", title="A", year=2023),
                record(paperId="W2", doi="https://doi.org/10.1/x", title="A", year=2023),
            ]
        )
        self.assertEqual(result["doi_duplicate_groups"], 1)
        self.assertEqual(result["title_duplicate_groups_merged"], 0)
        self.assertEqual(result["title_duplicate_groups"], [])


class TestBuildDb(unittest.TestCase):
    def test_empty_abstract_build_keeps_papers_and_fts_in_sync(self):
        papers = [
            record(
                paperId="W1", title="T", abstract=None, year=2023,
                matched_queries=["q"], matched_years=["2023"], run_id="r1",
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(os.path.join(tmp, "test.db"))
            inserted, skipped = build_db.rebuild(conn, papers, [])
            self.assertEqual(inserted, 1)
            self.assertEqual(skipped, [])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM papers_fts").fetchone()[0], 1)
            conn.close()

    def test_duplicate_primary_key_is_resolved_explicitly(self):
        papers = [
            record(paperId="W1", title="T", matched_queries=["q1"], run_id="r1"),
            record(paperId="W1", title="T", matched_queries=["q2"], run_id="r2"),
        ]
        resolved, skipped = build_db.resolve_papers(papers)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(sorted(resolved[0]["matched_queries"]), ["q1", "q2"])


if __name__ == "__main__":
    unittest.main()
