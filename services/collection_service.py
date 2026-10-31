import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from services import paper_service


def _load_screened_status(screened_path):
    path = Path(screened_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    papers = payload.get("papers") if isinstance(payload, dict) else payload
    if not isinstance(papers, list):
        return {}
    return {
        paper.get("paperId"): paper.get("relevance_status", "pending")
        for paper in papers
        if isinstance(paper, dict) and paper.get("paperId")
    }


SCHEMA = """
CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_items (
    collection_id INTEGER NOT NULL,
    paper_id TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (collection_id, paper_id),
    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(collection_items)")}
    if "reading_status" not in columns:
        conn.execute("ALTER TABLE collection_items ADD COLUMN reading_status TEXT DEFAULT 'to_read'")
    return conn


def list_collections(db_path):
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT c.id, c.name, c.description, c.created_at, c.updated_at, "
            "COUNT(i.paper_id) AS paper_count, MAX(i.added_at) AS last_added_at "
            "FROM collections c LEFT JOIN collection_items i ON i.collection_id = c.id "
            "GROUP BY c.id ORDER BY c.updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_collection(db_path, name, description=""):
    name = (name or "").strip()
    if not name:
        raise ValueError("collection name is required")
    conn = _connect(db_path)
    try:
        duplicate = conn.execute(
            "SELECT 1 FROM collections WHERE LOWER(name) = LOWER(?)",
            (name,),
        ).fetchone()
    finally:
        conn.close()
    if duplicate:
        raise ValueError("collection name already exists")
    now = _now()
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO collections (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, description.strip(), now, now),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_collection(db_path, papers_db, collection_id, screened_path=None):
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, description, created_at, updated_at FROM collections WHERE id = ?",
            (collection_id,),
        ).fetchone()
        if row is None:
            return None
        collection = dict(row)
        items = conn.execute(
            "SELECT paper_id, added_at, reading_status FROM collection_items WHERE collection_id = ? ORDER BY added_at DESC",
            (collection_id,),
        ).fetchall()
    finally:
        conn.close()

    papers = []
    status_map = _load_screened_status(screened_path) if screened_path else {}
    for item in items:
        paper = paper_service.get_paper(papers_db, item["paper_id"])
        if paper is not None:
            relevance_status = status_map.get(
                item["paper_id"], paper.get("relevance_status", "pending")
            )
            papers.append(
                {
                    "paper_id": item["paper_id"],
                    "title": paper.get("title"),
                    "authors": paper.get("authors"),
                    "year": paper.get("year"),
                    "venue": paper.get("venue"),
                    "relevance_status": relevance_status,
                    "added_at": item["added_at"],
                    "reading_status": item["reading_status"] or "to_read",
                }
            )
    collection["papers"] = papers
    return collection


def update_collection(db_path, collection_id, name=None, description=None):
    conn = _connect(db_path)
    try:
        existing = conn.execute(
            "SELECT name, description FROM collections WHERE id = ?", (collection_id,)
        ).fetchone()
        if existing is None:
            return None
        new_name = (name if name is not None else existing["name"]).strip()
        if not new_name:
            raise ValueError("collection name cannot be empty")
        new_description = (
            description if description is not None else existing["description"]
        ).strip()
        conn.execute(
            "UPDATE collections SET name = ?, description = ?, updated_at = ? WHERE id = ?",
            (new_name, new_description, _now(), collection_id),
        )
        conn.commit()
        return collection_id
    finally:
        conn.close()


def delete_collection(db_path, collection_id):
    conn = _connect(db_path)
    try:
        cursor = conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def add_paper(db_path, collection_id, paper_id, reading_status="to_read"):
    conn = _connect(db_path)
    try:
        exists = conn.execute(
            "SELECT 1 FROM collections WHERE id = ?", (collection_id,)
        ).fetchone()
        if exists is None:
            return None
        conn.execute(
            "INSERT OR IGNORE INTO collection_items (collection_id, paper_id, added_at, reading_status) "
            "VALUES (?, ?, ?, ?)",
            (collection_id, paper_id, _now(), reading_status),
        )
        conn.execute(
            "UPDATE collections SET updated_at = ? WHERE id = ?", (_now(), collection_id)
        )
        conn.commit()
        return collection_id
    finally:
        conn.close()


def remove_paper(db_path, collection_id, paper_id):
    conn = _connect(db_path)
    try:
        conn.execute(
            "DELETE FROM collection_items WHERE collection_id = ? AND paper_id = ?",
            (collection_id, paper_id),
        )
        conn.execute(
            "UPDATE collections SET updated_at = ? WHERE id = ?", (_now(), collection_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_or_create_default(db_path):
    name = "My Library"
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name FROM collections WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()
    finally:
        conn.close()
    if row:
        return row["id"], row["name"]
    collection_id = create_collection(db_path, name, "Default personal library")
    return collection_id, name


def quick_save(db_path, paper_id, collection_name=None):
    if collection_name:
        collection_id = create_collection(db_path, collection_name)
    else:
        collection_id, collection_name = get_or_create_default(db_path)
    add_paper(db_path, collection_id, paper_id)
    return {"collection_id": collection_id, "collection_name": collection_name}


def saved_collection_ids(db_path, paper_id):
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT collection_id FROM collection_items WHERE paper_id = ?", (paper_id,)
        ).fetchall()
        return [row["collection_id"] for row in rows]
    finally:
        conn.close()


def collection_paper_ids(db_path, collection_id):
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT paper_id FROM collection_items WHERE collection_id = ?", (collection_id,)
        ).fetchall()
        return [row["paper_id"] for row in rows]
    finally:
        conn.close()


def is_saved(db_path, paper_id):
    default_id, _ = get_or_create_default(db_path)
    return default_id in saved_collection_ids(db_path, paper_id)


def set_reading_status(db_path, collection_id, paper_id, reading_status):
    if reading_status not in {"to_read", "reading", "read"}:
        raise ValueError("invalid reading status")
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE collection_items SET reading_status = ? WHERE collection_id = ? AND paper_id = ?",
            (reading_status, collection_id, paper_id),
        )
        conn.execute(
            "UPDATE collections SET updated_at = ? WHERE id = ?", (_now(), collection_id)
        )
        conn.commit()
    finally:
        conn.close()


def export_citations(db_path, papers_db, collection_id):
    from services import ai_service

    conn = _connect(db_path)
    try:
        items = conn.execute(
            "SELECT paper_id FROM collection_items WHERE collection_id = ? ORDER BY added_at DESC",
            (collection_id,),
        ).fetchall()
    finally:
        conn.close()
    citations = []
    for item in items:
        paper = paper_service.get_paper(papers_db, item["paper_id"])
        if paper is not None:
            citations.append(
                {
                    "paper_id": paper.get("paper_id"),
                    "apa": ai_service.format_citation(paper, "apa"),
                    "ieee": ai_service.format_citation(paper, "ieee"),
                }
            )
    return citations
