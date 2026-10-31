import json
import sqlite3
from pathlib import Path


def _load_corpus(corpus_path):
    path = Path(corpus_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def get_paper(db_path, paper_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    paper = dict(row)
    paper["authors"] = json.loads(paper.get("authors_json") or "[]")
    paper["openalex_ids"] = json.loads(paper.get("openalex_ids_json") or "[]")
    paper["matched_queries"] = json.loads(paper.get("matched_queries_json") or "[]")
    paper["matched_years"] = json.loads(paper.get("matched_years_json") or "[]")
    paper["biblio"] = json.loads(paper.get("biblio_json") or "{}")
    return paper


def get_versions(db_path, corpus_path, paper_id):
    corpus = _load_corpus(corpus_path)
    groups = corpus.get("version_groups") or []
    group = None
    for candidate in groups:
        if paper_id in (candidate.get("paper_ids") or []):
            group = candidate
            break
    if group is None:
        return None

    members = []
    for member_id in group.get("paper_ids") or []:
        paper = get_paper(db_path, member_id)
        if paper is None:
            continue
        members.append(
            {
                "paper_id": member_id,
                "title": paper.get("title"),
                "year": paper.get("year"),
                "venue": paper.get("venue"),
                "doi": paper.get("doi"),
                "is_representative": member_id == group.get("representative_id"),
            }
        )
    return {
        "group_id": group.get("group_id"),
        "classification": group.get("classification"),
        "representative_id": group.get("representative_id"),
        "members": members,
    }


def get_stats(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"]
        years = conn.execute("SELECT MIN(year) AS min_year, MAX(year) AS max_year FROM papers").fetchone()
    finally:
        conn.close()
    return {
        "papers": count,
        "year_min": years["min_year"],
        "year_max": years["max_year"],
        "source": "OpenAlex",
    }
