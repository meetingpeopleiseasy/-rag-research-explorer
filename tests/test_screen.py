import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import screen_corpus


def paper(title, abstract=None, paper_type=None, venue=None, paper_id="W1"):
    return {
        "paperId": paper_id,
        "title": title,
        "abstract": abstract,
        "type": paper_type,
        "venue": venue,
        "year": 2024,
    }


class TestScreenPaper(unittest.TestCase):
    def test_clearly_relevant_included(self):
        status, reasons = screen_corpus.screen_paper(
            paper(
                "Retrieval-Augmented Generation for Question Answering",
                "We study retrieval-augmented generation methods.",
            )
        )
        self.assertEqual(status, "included")
        self.assertIn("explicit_rag_term", reasons)

    def test_clearly_irrelevant_excluded(self):
        status, reasons = screen_corpus.screen_paper(
            paper("Rag doll manufacturing", "Textile production techniques.")
        )
        self.assertEqual(status, "excluded")
        self.assertIn("non_rag_meaning", reasons)

    def test_abbreviation_only_uncertain(self):
        status, reasons = screen_corpus.screen_paper(
            paper("RAG: a study", "We evaluate RAG systems.")
        )
        self.assertEqual(status, "uncertain")
        self.assertIn("abbreviation_only", reasons)

    def test_missing_abstract_uncertain(self):
        status, reasons = screen_corpus.screen_paper(
            paper("Retrieval-Augmented Generation", abstract=None)
        )
        self.assertEqual(status, "uncertain")
        self.assertIn("abstract_missing", reasons)

    def test_unknown_doc_type(self):
        self.assertEqual(screen_corpus.classify_doc_type(paper("RAG survey")), "unknown")

    def test_single_word_ambiguous_title_is_marked(self):
        status, reasons = screen_corpus.screen_paper(paper("rag", abstract=None))
        self.assertEqual(status, "excluded")
        self.assertIn("short_title_ambiguous", reasons)

    def test_duplicate_records_are_screened_independently(self):
        a = paper("RAG: a study", "We evaluate RAG systems.", paper_id="W1")
        b = paper("RAG: a study", "We evaluate RAG systems.", paper_id="W1")
        screened = screen_corpus.screen_papers([a, b])
        self.assertEqual(len(screened), 2)
        self.assertEqual(screened[0]["relevance_status"], screened[1]["relevance_status"])


if __name__ == "__main__":
    unittest.main()
