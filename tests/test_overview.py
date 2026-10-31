import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("flask_app", ROOT / "app.py")
flask_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flask_app)

from services import ai_service  # noqa: E402


class TestOverviewAndQa(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = flask_app.create_app()
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()
        cls.papers = [
            "https://openalex.org/W4410877485",
            "https://openalex.org/W4393147129",
        ]

    def test_overview_citations_map_to_input_papers(self):
        with mock.patch.object(ai_service, "call_deepseek", return_value="Overview with [P1] and [P2]."):
            response = self.client.post(
                "/api/ai/research-overview",
                json={"query": "RAG evaluation", "paper_ids": self.papers},
            )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual([citation["paper_id"] for citation in data["citations"]], self.papers)
        self.assertEqual([citation["marker"] for citation in data["citations"]], ["P1", "P2"])
        self.assertIn("P1", data["content"])

    def test_qa_citations_map_to_input_papers(self):
        with mock.patch.object(ai_service, "call_deepseek", return_value="Answer mentions [P1]."):
            response = self.client.post(
                "/api/ai/qa",
                json={"question": "Which methods are compared?", "paper_ids": self.papers[:1]},
            )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["citations"]), 1)
        self.assertEqual(data["citations"][0]["paper_id"], self.papers[0])

    def test_missing_paper_returns_404(self):
        with mock.patch.object(ai_service, "call_deepseek", return_value="x"):
            response = self.client.post(
                "/api/ai/qa",
                json={"question": "q", "paper_ids": ["https://openalex.org/NOPE"]},
            )
        self.assertEqual(response.status_code, 404)

    def test_empty_paper_ids_returns_400(self):
        response = self.client.post(
            "/api/ai/qa",
            json={"question": "q", "paper_ids": []},
        )
        self.assertEqual(response.status_code, 400)

    def test_failure_path_returns_502(self):
        with mock.patch.object(ai_service, "call_deepseek", side_effect=RuntimeError("DeepSeek 请求超时")):
            response = self.client.post(
                "/api/ai/qa",
                json={"question": "q", "paper_ids": self.papers[:1]},
            )
        self.assertEqual(response.status_code, 502)
        self.assertIn("DeepSeek 请求超时", response.get_json()["error"])

    def test_overview_returns_structured_when_model_emits_json(self):
        json_content = (
            '{"Research Scope": "scope", "Research Directions": ["d1"], '
            '"Evidence Map": {"P1": "claim"}}'
        )
        with mock.patch.object(ai_service, "call_deepseek", return_value=json_content):
            response = self.client.post(
                "/api/ai/research-overview",
                json={"query": "RAG evaluation", "paper_ids": self.papers[:1]},
            )
        data = response.get_json()
        self.assertIsNotNone(data["structured"])
        self.assertEqual(data["structured"]["Research Scope"], "scope")

    def test_compare_citations_map_to_input_papers(self):
        json_content = (
            '{"dimensions": [{"dimension": "Research Question", '
            '"cells": {"P1": "Q1", "P2": "Q2"}}]}'
        )
        with mock.patch.object(ai_service, "call_deepseek", return_value=json_content):
            response = self.client.post(
                "/api/ai/compare",
                json={"paper_ids": self.papers},
            )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual([citation["paper_id"] for citation in data["citations"]], self.papers)
        self.assertEqual(data["structured"]["dimensions"][0]["cells"]["P1"], "Q1")

    def test_compare_requires_two_to_five_papers(self):
        response = self.client.post("/api/ai/compare", json={"paper_ids": self.papers[:1]})
        self.assertEqual(response.status_code, 400)

    def test_citations_include_doi_and_formats(self):
        paper = {
            "paper_id": "W1",
            "title": "A Paper",
            "year": 2024,
            "authors": ["Alice"],
            "venue": None,
            "doi": "10.1/x",
        }
        citations = ai_service._citations([paper])
        self.assertEqual(citations[0]["doi_url"], "https://doi.org/10.1/x")
        self.assertIn("[missing venue]", citations[0]["apa"])
        self.assertIn("doi: 10.1/x", citations[0]["ieee"])

    def test_context_keeps_history_server_side(self):
        paper = {
            "paper_id": "W1",
            "title": "A Paper",
            "abstract": "abstract",
            "authors": ["Alice"],
            "year": 2024,
            "venue": "v",
            "doi": "10.1/x",
        }
        context_id, info = ai_service.create_context("q", [paper])
        with mock.patch.object(ai_service, "call_deepseek", return_value="answer"):
            first = ai_service.answer_followup(context_id, "question 1")
            second = ai_service.answer_followup(context_id, "question 2")
        self.assertEqual(info["paper_count"], 1)
        self.assertEqual(first["content"], "answer")
        self.assertEqual(len(ai_service.get_context(context_id)["history"]), 2)
        self.assertTrue(ai_service.clear_context(context_id))


if __name__ == "__main__":
    unittest.main()
