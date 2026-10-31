#!/usr/bin/env python3
"""Build a SQLite + FTS5 database from data/corpus.json."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import corpus


SCHEMA = """
CREATE TABLE papers (
    paper_id TEXT PRIMARY KEY,
    title TEXT,
    abstract TEXT,
    year INTEGER,
    publication_date TEXT,
    doi TEXT,
    venue TEXT,
    type TEXT,
    language TEXT,
    cited_by_count INTEGER,
    authors_json TEXT,
    biblio_json TEXT,
    source TEXT,
    normalized_title TEXT,
    matched_queries_json TEXT,
    matched_years_json TEXT,
    run_ids_json TEXT,
    openalex_ids_json TEXT,
    dedup_status TEXT,
    relevance_status TEXT
);

CREATE VIRTUAL TABLE papers_fts USING fts5(
    paper_id UNINDEXED,
    title,
    abstract
);

CREATE TABLE conflicts (
    conflict_id TEXT PRIMARY KEY,
    reason TEXT,
    paper_ids_json TEXT,
    fields_json TEXT
);
"""


def load_corpus(corpus_path):
    payload = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    papers = payload.get("papers") if isinstance(payload, dict) else payload
    conflicts = payload.get("conflicts") if isinstance(payload, dict) else []
    if not isinstance(papers, list):
        raise ValueError(f"{corpus_path} 中没有 `papers` 列表")
    return papers, conflicts or []


def fallback_key(paper):
    doi = corpus.normalize_doi_value(
        paper.get("doi") or (paper.get("externalIds") or {}).get("DOI")
    )
    if doi:
        return f"doi:{doi}"
    title = corpus.normalize_title(paper.get("title"))
    if title:
        return f"title:{title}"
    digest = hashlib.sha256(
        json.dumps(paper, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]
    return f"no-id:{digest}"


def resolve_papers(papers):
    """Resolve duplicate primary keys explicitly; never silently overwrite."""
    resolved = {}
    skipped = []
    for paper in papers:
        primary_key = paper.get("paperId") or fallback_key(paper)
        if primary_key in resolved:
            existing = resolved[primary_key]
            existing["matched_queries"] = corpus.merge_unique(
                existing.get("matched_queries"), paper.get("matched_queries")
            )
            existing["matched_years"] = corpus.merge_unique(
                existing.get("matched_years"), paper.get("matched_years")
            )
            existing["run_ids"] = corpus.merge_unique(
                existing.get("run_ids"), paper.get("run_ids")
            )
            existing["openalex_ids"] = corpus.merge_unique(
                existing.get("openalex_ids"), paper.get("openalex_ids")
            )
            skipped.append({"primary_key": primary_key, "paper_id": paper.get("paperId")})
        else:
            resolved[primary_key] = paper
    return list(resolved.values()), skipped


def rebuild(conn, papers, conflicts):
    conn.execute("DROP TABLE IF EXISTS papers")
    conn.execute("DROP TABLE IF EXISTS papers_fts")
    conn.execute("DROP TABLE IF EXISTS conflicts")
    conn.executescript(SCHEMA)

    resolved_papers, skipped = resolve_papers(papers)
    for paper in resolved_papers:
        primary_key = paper.get("paperId") or fallback_key(paper)
        conn.execute(
            "INSERT INTO papers (paper_id, title, abstract, year, publication_date, "
            "doi, venue, type, language, cited_by_count, authors_json, biblio_json, source, "
            "normalized_title, matched_queries_json, matched_years_json, run_ids_json, "
            "openalex_ids_json, dedup_status, relevance_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                primary_key,
                paper.get("title"),
                paper.get("abstract"),
                paper.get("year"),
                paper.get("publicationDate"),
                paper.get("doi") or (paper.get("externalIds") or {}).get("DOI"),
                paper.get("venue"),
                paper.get("type"),
                paper.get("language"),
                paper.get("citedByCount"),
                json.dumps(paper.get("authors") or [], ensure_ascii=False),
                json.dumps(paper.get("biblio") or {}, ensure_ascii=False),
                paper.get("source"),
                paper.get("normalized_title") or corpus.normalize_title(paper.get("title")),
                json.dumps(paper.get("matched_queries") or [], ensure_ascii=False),
                json.dumps(paper.get("matched_years") or [], ensure_ascii=False),
                json.dumps(paper.get("run_ids") or [], ensure_ascii=False),
                json.dumps(paper.get("openalex_ids") or [], ensure_ascii=False),
                paper.get("dedup_status"),
                paper.get("relevance_status") or "pending",
            ),
        )
        conn.execute(
            "INSERT INTO papers_fts (paper_id, title, abstract) VALUES (?, ?, ?)",
            (primary_key, paper.get("title"), paper.get("abstract")),
        )

    for conflict in conflicts:
        conn.execute(
            "INSERT INTO conflicts (conflict_id, reason, paper_ids_json, fields_json) "
            "VALUES (?, ?, ?, ?)",
            (
                conflict.get("group_id"),
                conflict.get("reason"),
                json.dumps(conflict.get("paper_ids") or [], ensure_ascii=False),
                json.dumps(conflict.get("fields") or [], ensure_ascii=False),
            ),
        )

    conn.commit()
    return len(resolved_papers), skipped


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="从候选语料构建 SQLite + FTS5 数据库。")
    parser.add_argument("--corpus", default="data/corpus.json",
                        help="候选语料 JSON，默认 data/corpus.json")
    parser.add_argument("--db", default="data/papers.db",
                        help="SQLite 数据库路径，默认 data/papers.db")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    corpus_path = Path(args.corpus)
    if not corpus_path.exists():
        raise SystemExit(
            f"未找到 {corpus_path}，请先运行 `python scripts/merge_corpus.py`。"
        )

    papers, conflicts = load_corpus(corpus_path)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        inserted, skipped = rebuild(conn, papers, conflicts)
    finally:
        conn.close()

    print(f"已把 {inserted} 篇候选论文写入 {db_path}，显式跳过重复主键 {len(skipped)} 条")
    for item in skipped[:10]:
        print(f"  重复主键: {item['primary_key']}（paper_id={item['paper_id']}）")
    print("FTS5 索引已建立，覆盖 title 与 abstract。")


if __name__ == "__main__":
    main()
