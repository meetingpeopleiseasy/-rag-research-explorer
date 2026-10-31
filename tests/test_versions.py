import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import corpus
import search_papers


def paper(paper_id, title, authors, abstract, venue, doi=None):
    return {
        "paperId": paper_id,
        "title": title,
        "normalized_title": corpus.normalize_title(title),
        "authors": authors,
        "abstract": abstract,
        "venue": venue,
        "doi": doi,
    }


def row(paper_id, title, doi, score=-1.0, normalized_title=None):
    return (
        paper_id,
        title,
        2024,
        "venue",
        doi,
        0,
        "snippet",
        score,
        normalized_title or title.lower(),
    )


class TestVersionGroups(unittest.TestCase):
    def test_confirmed_version_group_prefers_formal_venue(self):
        a = paper(
            "W1", "LiveRAG benchmark", ["Carmel, David", "Filice, Simone"],
            "Retrieval Augmented Generation benchmark", "arXiv (Cornell University)",
            "https://doi.org/10.48550/arxiv.2511.14531",
        )
        b = paper(
            "W2", "LiveRAG benchmark", ["David Carmel", "Simone Filice"],
            "Retrieval Augmented Generation benchmark", "International ACM SIGIR Conference",
            "https://doi.org/10.1145/3805712.3808585",
        )
        groups = corpus.build_version_groups([a, b])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["classification"], "confirmed_same_work")
        self.assertEqual(groups[0]["representative_id"], "W2")

    def test_same_title_but_different_authors_and_abstract_not_grouped(self):
        a = paper("W1", "RAG survey", ["Alice"], "about apples", "Journal A")
        b = paper("W2", "RAG survey", ["Bob"], "about bananas", "Journal B")
        self.assertEqual(corpus.build_version_groups([a, b]), [])

    def test_insufficient_evidence_is_suspected(self):
        a = paper("W1", "RAG survey", [], None, None)
        b = paper("W2", "RAG survey", [], None, None)
        groups = corpus.build_version_groups([a, b])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["classification"], "suspected_same_work")

    def test_short_title_unrelated_works_do_not_form_version_group(self):
        a = paper("W1", "rag", [], None, "Fairchild Books")
        b = paper("W2", "Rag", [], None, None)
        self.assertEqual(corpus.build_version_groups([a, b]), [])

    def test_short_title_with_strong_author_and_abstract_evidence_groups(self):
        a = paper(
            "W1", "RAG", ["Alice", "Bob"],
            "Retrieval augmented generation for question answering", "arXiv (Cornell University)",
        )
        b = paper(
            "W2", "RAG", ["Alice", "Bob"],
            "Retrieval augmented generation for question answering", "ACL",
        )
        groups = corpus.build_version_groups([a, b])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["classification"], "confirmed_same_work")

    def test_short_title_with_same_doi_groups(self):
        a = {**paper("W1", "rag", [], None, None), "doi_norm": "10.1/x"}
        b = {**paper("W2", "RAG", [], None, None), "doi_norm": "10.1/x"}
        groups = corpus.build_version_groups([a, b])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["classification"], "confirmed_same_work")


class TestVersionDisplay(unittest.TestCase):
    def test_confirmed_versions_collapse_without_losing_records(self):
        rows = [
            row("W1", "LiveRAG benchmark", "https://doi.org/10.48550/arxiv.2511.14531", score=-2.0),
            row("W2", "LiveRAG benchmark", "https://doi.org/10.1145/3805712.3808585", score=-3.0),
        ]
        version_groups = [
            {
                "group_id": "version-1",
                "classification": "confirmed_same_work",
                "paper_ids": ["W1", "W2"],
                "representative_id": "W2",
            }
        ]
        entries = search_papers.group_results(rows, version_groups)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["duplicate_kind"], "confirmed_same_work")
        self.assertEqual(sorted(entries[0]["member_ids"]), ["W1", "W2"])

    def test_suspected_versions_are_marked_not_merged(self):
        rows = [
            row("W1", "RAG survey", "https://doi.org/10.1/x", score=-2.0),
            row("W2", "RAG survey", "https://doi.org/10.2/y", score=-3.0),
        ]
        version_groups = [
            {
                "group_id": "version-1",
                "classification": "suspected_same_work",
                "paper_ids": ["W1", "W2"],
                "representative_id": "W1",
            }
        ]
        entries = search_papers.group_results(rows, version_groups)
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            {entry["duplicate_kind"] for entry in entries},
            {"suspected_same_work"},
        )

    def test_different_work_review_dissolves_title_suspicion(self):
        rows = [
            row("W1", "RAG survey", "https://doi.org/10.1/x", score=-2.0),
            row("W2", "RAG survey", "https://doi.org/10.2/y", score=-3.0),
        ]
        different_work_groups = [{"group_id": "dw-1", "paper_ids": ["W1", "W2"]}]
        entries = search_papers.group_results(rows, None, different_work_groups)
        self.assertEqual(len(entries), 2)
        self.assertEqual({entry["duplicate_kind"] for entry in entries}, {"none"})


class TestApplyReview(unittest.TestCase):
    def _groups(self):
        return [
            {"group_id": "version-1", "classification": "suspected_same_work", "paper_ids": ["W1", "W2"]},
            {"group_id": "version-2", "classification": "suspected_same_work", "paper_ids": ["W3", "W4"]},
            {"group_id": "version-3", "classification": "suspected_same_work", "paper_ids": ["W5", "W6"]},
            {"group_id": "version-4", "classification": "suspected_same_work", "paper_ids": ["W7", "W8"]},
        ]

    def test_same_work_promotes_to_confirmed(self):
        result = corpus.apply_version_review(self._groups(), {"version-1": "same_work"})
        self.assertEqual(result["version_groups"][0]["classification"], "confirmed_same_work")
        self.assertEqual(result["different_work_groups"], [])

    def test_different_work_dissolves_group(self):
        result = corpus.apply_version_review(self._groups(), {"version-2": "different_work"})
        self.assertEqual(len(result["version_groups"]), 3)
        self.assertEqual(result["different_work_groups"][0]["group_id"], "version-2")

    def test_uncertain_keeps_suspected(self):
        result = corpus.apply_version_review(self._groups(), {"version-3": "uncertain"})
        updated = next(g for g in result["version_groups"] if g["group_id"] == "version-3")
        self.assertEqual(updated["classification"], "suspected_same_work")
        self.assertEqual(updated["review_decision"], "uncertain")

    def test_pending_and_unknown_leave_auto_decision(self):
        result = corpus.apply_version_review(self._groups(), {"version-4": "pending"})
        updated = next(g for g in result["version_groups"] if g["group_id"] == "version-4")
        self.assertEqual(updated["classification"], "suspected_same_work")
        self.assertNotIn("review_decision", updated)

    def test_apply_review_is_idempotent(self):
        decisions = {"version-1": "same_work", "version-2": "different_work", "version-3": "uncertain"}
        once = corpus.apply_version_review(self._groups(), decisions)
        twice = corpus.apply_version_review(self._groups(), decisions)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
