import json
import re
import sqlite3
from pathlib import Path

import search_papers


SEARCH_SELECT = """
SELECT p.paper_id, p.title, p.year, p.venue, p.doi, p.cited_by_count,
       snippet(papers_fts, 2, '<mark>', '</mark>', '…', 24) AS snippet,
       rank AS score, p.normalized_title, p.authors_json,
       p.relevance_status, p.openalex_ids_json, p.dedup_status
FROM papers_fts
JOIN papers p ON p.paper_id = papers_fts.paper_id
"""


def _load_group_info(corpus_path):
    path = Path(corpus_path)
    if not path.exists():
        return [], []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return [], []
    version_groups = payload.get("version_groups") or []
    different_work_groups = payload.get("different_work_groups") or []
    return (
        version_groups if isinstance(version_groups, list) else [],
        different_work_groups if isinstance(different_work_groups, list) else [],
    )


def get_filter_options(screened_path):
    _, doc_type_map = _load_screened_meta(screened_path)
    return {
        "years": [str(year) for year in range(2021, 2027)],
        "doc_types": sorted({value for value in doc_type_map.values() if value}),
        "statuses": ["included", "uncertain", "excluded", "pending"],
    }


def _load_screened_meta(screened_path):
    path = Path(screened_path)
    if not path.exists():
        return {}, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    papers = payload.get("papers") if isinstance(payload, dict) else payload
    if not isinstance(papers, list):
        return {}, {}
    status = {}
    doc_types = {}
    for paper in papers:
        if isinstance(paper, dict) and paper.get("paperId"):
            paper_id = paper["paperId"]
            status[paper_id] = paper.get("relevance_status", "pending")
            doc_types[paper_id] = paper.get("doc_type")
    return status, doc_types


def _highlight(text, query):
    if not isinstance(text, str) or not query:
        return text
    tokens = [token for token in re.findall(r"[A-Za-z0-9]+", query) if len(token) >= 2]
    if not tokens:
        return text
    pattern = re.compile("|".join(re.escape(token) for token in tokens), re.IGNORECASE)
    return pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", text)


def _row_to_dict(row):
    item = dict(row)
    item["authors"] = json.loads(item.get("authors_json") or "[]")
    item["openalex_ids"] = json.loads(item.get("openalex_ids_json") or "[]")
    return item


def _group_rows(rows, version_groups, different_work_groups):
    tuples = [
        (
            row["paper_id"],
            row["title"],
            row["year"],
            row["venue"],
            row["doi"],
            row["cited_by_count"],
            row["snippet"],
            row["score"],
            row["normalized_title"],
        )
        for row in rows
    ]
    entries = search_papers.group_results(tuples, version_groups or None, different_work_groups or None)
    by_id = {row["paper_id"]: row for row in rows}
    grouped = []
    for entry in entries:
        item = dict(by_id.get(entry["paper_id"], {}))
        item["duplicate_kind"] = entry.get("duplicate_kind", "none")
        if "member_ids" in entry:
            item["member_ids"] = entry["member_ids"]
        if "version_group_id" in entry:
            item["version_group_id"] = entry["version_group_id"]
        if "suspected_group_id" in entry:
            item["suspected_group_id"] = entry["suspected_group_id"]
        grouped.append(item)
    return grouped


def search_documents(
    db_path,
    corpus_path,
    query,
    page=1,
    per_page=10,
    year=None,
    years=None,
    year_from=None,
    year_to=None,
    doc_types=None,
    statuses=None,
    screened_path=None,
):
    fts_query = search_papers.build_fts_query(query)
    where = "WHERE papers_fts MATCH ?"
    params = [fts_query]

    clauses = []
    year_values = [int(value) for value in (years or []) if value]
    if not year_values and year:
        year_values = [int(year)]
    if year_values:
        placeholders = ",".join("?" for _ in year_values)
        clauses.append(f"p.year IN ({placeholders})")
        params.extend(year_values)
    if year_from is not None:
        clauses.append("p.year >= ?")
        params.append(int(year_from))
    if year_to is not None:
        clauses.append("p.year <= ?")
        params.append(int(year_to))

    status_map, doc_type_map = _load_screened_meta(screened_path) if screened_path else ({}, {})
    selected_doc_types = set(doc_types or [])
    selected_statuses = set(statuses or [])
    if selected_doc_types or selected_statuses:
        allowed = None
        for selected, mapping in (
            (selected_doc_types, doc_type_map),
            (selected_statuses, status_map),
        ):
            if not selected:
                continue
            ids = {paper_id for paper_id, value in mapping.items() if value in selected}
            allowed = ids if allowed is None else (allowed & ids)
        allowed = allowed or set()
        placeholders = ",".join("?" for _ in allowed)
        clauses.append(f"p.paper_id IN ({placeholders})")
        params.extend(sorted(allowed))

    if clauses:
        where += " AND " + " AND ".join(clauses)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM papers_fts JOIN papers p ON p.paper_id = papers_fts.paper_id {where}",
            params,
        ).fetchone()["n"]
        offset = (page - 1) * per_page
        rows = conn.execute(
            f"{SEARCH_SELECT} {where} ORDER BY rank LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
    finally:
        conn.close()

    documents = [_row_to_dict(row) for row in rows]
    for document in documents:
        document["title_highlighted"] = _highlight(document.get("title"), query)
        document["relevance_status"] = status_map.get(
            document["paper_id"], document.get("relevance_status", "pending")
        )
        document["doc_type"] = doc_type_map.get(document["paper_id"])

    version_groups, different_work_groups = _load_group_info(corpus_path)
    results = _group_rows(documents, version_groups, different_work_groups)
    return {
        "query": query,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "year": year,
        "years": years,
        "year_from": year_from,
        "year_to": year_to,
        "doc_types": doc_types,
        "statuses": statuses,
        "results": results,
    }
