import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import search_papers


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


class TestGroupResults(unittest.TestCase):
    def test_same_doi_is_grouped_without_losing_rows(self):
        rows = [
            row("W1", "RAG survey", "https://doi.org/10.1/x", score=-2.0),
            row("W2", "RAG survey", "https://doi.org/10.1/X", score=-3.0),
        ]
        entries = search_papers.group_results(rows)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["duplicate_kind"], "same_doi")
        self.assertEqual(sorted(entries[0]["member_ids"]), ["W1", "W2"])

    def test_different_doi_same_title_is_suspected_not_merged(self):
        rows = [
            row("W1", "RAG survey", "https://doi.org/10.1/x", score=-2.0),
            row("W2", "RAG survey", "https://doi.org/10.2/y", score=-3.0),
        ]
        entries = search_papers.group_results(rows)
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            {entry["duplicate_kind"] for entry in entries},
            {"suspected_duplicate"},
        )
        group_ids = {entry["suspected_group_id"] for entry in entries}
        self.assertEqual(len(group_ids), 1)

    def test_no_record_is_lost_across_grouping(self):
        rows = [
            row("W1", "RAG survey", "https://doi.org/10.1/x", score=-2.0),
            row("W2", "RAG survey", "https://doi.org/10.1/x", score=-3.0),
            row("W3", "RAG survey", "https://doi.org/10.2/y", score=-4.0),
            row("W4", "Unique paper", None, score=-5.0),
        ]
        entries = search_papers.group_results(rows)
        seen_ids = set()
        for entry in entries:
            if "member_ids" in entry:
                seen_ids.update(entry["member_ids"])
            else:
                seen_ids.add(entry["paper_id"])
        self.assertEqual(seen_ids, {"W1", "W2", "W3", "W4"})


if __name__ == "__main__":
    unittest.main()
