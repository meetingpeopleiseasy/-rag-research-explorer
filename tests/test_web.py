import json
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("flask_app", ROOT / "app.py")
flask_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flask_app)
create_app = flask_app.create_app

from services import search_service  # noqa: E402


class TestWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()
        cls.db = cls.app.config["DB_PATH"]
        cls.corpus = cls.app.config["CORPUS_PATH"]

    def test_home_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"RAG Research Explorer", response.data)

    def test_api_search_returns_results(self):
        response = self.client.get("/api/search?q=retrieval%20augmented")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertGreater(payload["total"], 0)
        self.assertTrue(payload["results"])

    def test_empty_and_special_query_do_not_500(self):
        self.assertEqual(self.client.get("/api/search?q=").status_code, 400)
        response = self.client.get("/api/search?q=:")
        self.assertEqual(response.status_code, 400)

    def test_pagination(self):
        first = self.client.get("/api/search?q=retrieval&per_page=3&page=1").get_json()
        second = self.client.get("/api/search?q=retrieval&per_page=3&page=2").get_json()
        first_ids = {item["paper_id"] for item in first["results"]}
        second_ids = {item["paper_id"] for item in second["results"]}
        self.assertEqual(len(first["results"]), 3)
        self.assertEqual(len(second["results"]), 3)
        self.assertTrue(first_ids.isdisjoint(second_ids))

    def test_year_filter(self):
        payload = self.client.get("/api/search?q=retrieval&year=2021&per_page=5").get_json()
        self.assertGreater(len(payload["results"]), 0)
        self.assertTrue(all(item["year"] == 2021 for item in payload["results"]))

    def test_paper_detail_by_openalex_id(self):
        response = self.client.get("/api/paper/https://openalex.org/W4410877485")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["paper"]["paper_id"], "https://openalex.org/W4410877485")

    def test_invalid_paper_id_returns_404(self):
        self.assertEqual(self.client.get("/api/paper/not-a-real-id").status_code, 404)
        self.assertEqual(self.client.get("/paper/not-a-real-id").status_code, 404)

    def test_version_folding_keeps_members(self):
        data = search_service.search_documents(
            self.db,
            self.corpus,
            "Uncertainty Quantification for Multimodal Retrieval Augmented Generation",
            page=1,
            per_page=10,
        )
        folded = [
            item for item in data["results"]
            if item.get("duplicate_kind") == "confirmed_same_work"
        ]
        self.assertTrue(folded)
        for item in folded:
            self.assertIn("member_ids", item)
            self.assertGreaterEqual(len(item["member_ids"]), 2)

    def test_api_key_not_exposed(self):
        response = self.client.get("/")
        self.assertNotIn(b"DEEPSEEK_API_KEY", response.data)
        payload = self.client.get("/api/search?q=rag").get_json()
        self.assertNotIn("api_key", json.dumps(payload))

    def test_ai_markdown_renderer_escapes_html(self):
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function escapeHtml", script)
        self.assertIn("function safeMarkdown", script)
        self.assertIn("output.innerHTML = safeMarkdown", script)
        self.assertIn(".replace(/&/g, \"&amp;\")", script)


if __name__ == "__main__":
    unittest.main()
