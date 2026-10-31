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

from services import collection_service  # noqa: E402


def _make_papers_db(tmpdir):
    db = os.path.join(tmpdir, "papers.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE papers (paper_id TEXT PRIMARY KEY, title TEXT, abstract TEXT, year INTEGER, "
        "venue TEXT, doi TEXT, cited_by_count INTEGER, authors_json TEXT, biblio_json TEXT, source TEXT, "
        "normalized_title TEXT, matched_queries_json TEXT, matched_years_json TEXT, run_ids_json TEXT, "
        "openalex_ids_json TEXT, dedup_status TEXT, relevance_status TEXT)"
    )
    conn.execute(
        "INSERT INTO papers (paper_id, title, year, authors_json, openalex_ids_json, relevance_status) "
        "VALUES ('W1', 'Paper one', 2024, '[\"Alice\"]', '[\"W1\"]', 'included')"
    )
    conn.commit()
    conn.close()
    return db


class TestCollectionService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.collections_db = os.path.join(cls.tmp.name, "collections.db")
        cls.papers_db = _make_papers_db(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_create_and_get(self):
        collection_id = collection_service.create_collection(self.collections_db, "RAG Evaluation", "eval papers")
        collection = collection_service.get_collection(self.collections_db, self.papers_db, collection_id)
        self.assertEqual(collection["name"], "RAG Evaluation")
        self.assertEqual(collection["papers"], [])

    def test_add_duplicate_is_idempotent(self):
        collection_id = collection_service.create_collection(self.collections_db, "C")
        collection_service.add_paper(self.collections_db, collection_id, "W1")
        collection_service.add_paper(self.collections_db, collection_id, "W1")
        collection = collection_service.get_collection(self.collections_db, self.papers_db, collection_id)
        self.assertEqual(len(collection["papers"]), 1)

    def test_remove_paper(self):
        collection_id = collection_service.create_collection(self.collections_db, "C2")
        collection_service.add_paper(self.collections_db, collection_id, "W1")
        collection_service.remove_paper(self.collections_db, collection_id, "W1")
        collection = collection_service.get_collection(self.collections_db, self.papers_db, collection_id)
        self.assertEqual(collection["papers"], [])

    def test_delete_collection_does_not_touch_papers(self):
        collection_id = collection_service.create_collection(self.collections_db, "C3")
        collection_service.add_paper(self.collections_db, collection_id, "W1")
        self.assertTrue(collection_service.delete_collection(self.collections_db, collection_id))
        self.assertIsNone(collection_service.get_collection(self.collections_db, self.papers_db, collection_id))

    def test_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            collection_service.create_collection(self.collections_db, "   ")

    def test_duplicate_name_rejected(self):
        collection_service.create_collection(self.collections_db, "Duplicate Name Check")
        with self.assertRaises(ValueError):
            collection_service.create_collection(self.collections_db, "duplicate name check")

    def test_default_library_is_idempotent(self):
        first_id, first_name = collection_service.get_or_create_default(self.collections_db)
        second_id, second_name = collection_service.get_or_create_default(self.collections_db)
        self.assertEqual(first_id, second_id)
        self.assertEqual(first_name, "My Library")

    def test_quick_save_is_idempotent(self):
        result = collection_service.quick_save(self.collections_db, "W1")
        again = collection_service.quick_save(self.collections_db, "W1")
        self.assertEqual(result["collection_name"], "My Library")
        collection = collection_service.get_collection(
            self.collections_db, self.papers_db, result["collection_id"]
        )
        self.assertEqual(len(collection["papers"]), 1)

    def test_quick_save_to_named_collection(self):
        result = collection_service.quick_save(self.collections_db, "W1", collection_name="Eval")
        self.assertEqual(result["collection_name"], "Eval")

    def test_export_citations_and_reading_status(self):
        collection_id = collection_service.create_collection(self.collections_db, "Export")
        collection_service.add_paper(self.collections_db, collection_id, "W1")
        citations = collection_service.export_citations(self.collections_db, self.papers_db, collection_id)
        self.assertEqual(len(citations), 1)
        self.assertIn("apa", citations[0])
        collection_service.set_reading_status(self.collections_db, collection_id, "W1", "read")
        collection = collection_service.get_collection(self.collections_db, self.papers_db, collection_id)
        self.assertEqual(collection["papers"][0]["reading_status"], "read")


class TestCollectionApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.papers_db = _make_papers_db(cls.tmp.name)
        cls.app = flask_app.create_app()
        cls.app.config.update(
            TESTING=True,
            DB_PATH=cls.papers_db,
            COLLECTIONS_PATH=os.path.join(cls.tmp.name, "collections.db"),
        )
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_create_add_get_delete_flow(self):
        created = self.client.post("/api/collections", json={"name": "RAG Evaluation"}).get_json()
        collection_id = created["id"]
        response = self.client.post(f"/api/collections/{collection_id}/papers", json={"paper_id": "W1"})
        self.assertEqual(response.status_code, 200)
        detail = self.client.get(f"/api/collections/{collection_id}").get_json()
        self.assertEqual(len(detail["papers"]), 1)
        self.assertEqual(self.client.delete(f"/api/collections/{collection_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/collections/{collection_id}").status_code, 404)

    def test_add_invalid_paper(self):
        created = self.client.post("/api/collections", json={"name": "C"}).get_json()
        response = self.client.post(f"/api/collections/{created['id']}/papers", json={"paper_id": "NOPE"})
        self.assertEqual(response.status_code, 404)

    def test_quick_save_api(self):
        response = self.client.post("/api/collections/quick-save", json={"paper_id": "W1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["collection_name"], "My Library")


if __name__ == "__main__":
    unittest.main()
