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


class TestAiPaperAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = flask_app.create_app()
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()
        cls.paper_id = "https://openalex.org/W4410877485"

    def test_success_path(self):
        with mock.patch.object(ai_service, "call_deepseek", return_value="A concise summary."):
            response = self.client.post(
                "/api/ai/paper-analysis",
                json={"paper_id": self.paper_id, "analysis_type": "tldr"},
            )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["content"], "A concise summary.")
        self.assertEqual(data["basis"], "Abstract / Metadata")
        self.assertNotIn("api_key", str(data))

    def test_failure_path(self):
        with mock.patch.object(ai_service, "call_deepseek", side_effect=RuntimeError("DeepSeek 请求超时")):
            response = self.client.post(
                "/api/ai/paper-analysis",
                json={"paper_id": self.paper_id, "analysis_type": "tldr"},
            )
        self.assertEqual(response.status_code, 502)
        self.assertIn("DeepSeek 请求超时", response.get_json()["error"])

    def test_invalid_analysis_type(self):
        response = self.client.post(
            "/api/ai/paper-analysis",
            json={"paper_id": self.paper_id, "analysis_type": "bogus"},
        )
        self.assertEqual(response.status_code, 400)

    def test_paper_not_found(self):
        response = self.client.post(
            "/api/ai/paper-analysis",
            json={"paper_id": "https://openalex.org/NOPE", "analysis_type": "tldr"},
        )
        self.assertEqual(response.status_code, 404)

    def test_cache_avoids_duplicate_request(self):
        with mock.patch.object(ai_service, "call_deepseek", return_value="cached answer") as mocked:
            first = self.client.post(
                "/api/ai/paper-analysis",
                json={"paper_id": self.paper_id, "analysis_type": "methodology"},
            )
            second = self.client.post(
                "/api/ai/paper-analysis",
                json={"paper_id": self.paper_id, "analysis_type": "methodology"},
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["cached"])
        self.assertEqual(mocked.call_count, 1)


if __name__ == "__main__":
    unittest.main()
