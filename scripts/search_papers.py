#!/usr/bin/env python3
"""Full-text search over the SQLite FTS5 index built by build_db.py."""

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

import corpus


SEARCH_SQL = """
SELECT p.paper_id,
       p.title,
       p.year,
       p.venue,
       p.doi,
       p.cited_by_count,
       snippet(papers_fts, 2, '[', ']', '…', 24) AS abstract_snippet,
       rank AS score,
       p.normalized_title
FROM papers_fts
JOIN papers p ON p.paper_id = papers_fts.paper_id
WHERE papers_fts MATCH ?
ORDER BY rank
LIMIT ?
"""


def build_fts_query(text, advanced=False):
    """Turn user input into an FTS5 MATCH expression.

    Normal mode strips FTS5 operator characters so natural-language input
    (hyphens, colons, parentheses, quotes) can't be misread as FTS5 syntax.
    Advanced mode passes the input through unchanged for phrase / prefix /
    boolean queries.
    """
    if not isinstance(text, str):
        text = ""
    if advanced:
        query = text.strip()
    else:
        query = re.sub(r"[^\w\s]", " ", text)
        query = re.sub(r"\s+", " ", query).strip()
    if not query:
        raise ValueError("查询为空，请输入检索词。")
    return query


def _execute(conn, fts_query, limit):
    try:
        return conn.execute(SEARCH_SQL, (fts_query, limit)).fetchall()
    except sqlite3.OperationalError as exc:
        raise ValueError(
            "FTS5 查询语法错误，无法解析该查询。\n"
            "提示：短语用双引号，如 \"retrieval augmented\"；词尾用 * 做前缀；"
            "可用 AND / OR / NOT 组合。请检查语法后重试。"
        ) from exc


def search(db_path, query, limit=10, advanced=False):
    fts_query = build_fts_query(query, advanced)
    conn = sqlite3.connect(db_path)
    try:
        return _execute(conn, fts_query, limit)
    finally:
        conn.close()


def group_results(rows, version_groups=None, different_work_groups=None):
    """Group confirmed duplicates and mark suspected ones without dropping rows.

    `rows` are 9-tuples from SEARCH_SQL:
    (paper_id, title, year, venue, doi, cited_by_count, snippet, score,
     normalized_title). Same normalized DOI (or same OpenAlex ID) is treated
    as the same record and grouped. `version_groups` (from corpus.json) can
    collapse confirmed versions of the same work or mark suspected versions.
    """
    records = []
    for row in rows:
        paper_id, title, year, venue, doi, cited_by_count, snippet, score, normalized_title = row
        records.append(
            {
                "paper_id": paper_id,
                "title": title,
                "year": year,
                "venue": venue,
                "doi": doi,
                "cited_by_count": cited_by_count,
                "snippet": snippet,
                "score": score,
                "normalized_title": normalized_title,
                "doi_norm": corpus.normalize_doi_value(doi),
            }
        )

    confirm_index = defaultdict(list)
    for index, record in enumerate(records):
        if record["doi_norm"]:
            confirm_index[("doi", record["doi_norm"])].append(index)
        elif record["paper_id"]:
            confirm_index[("id", record["paper_id"])].append(index)

    grouped = {}
    group_members = {}
    for key, indices in confirm_index.items():
        if len(indices) < 2:
            continue
        first = indices[0]
        for index in indices:
            grouped[index] = first
        group_members[first] = [records[index]["paper_id"] for index in indices]

    version_map = {}
    if version_groups:
        for group in version_groups:
            for paper_id in group.get("paper_ids") or []:
                version_map[paper_id] = group

    dissolved_groups = {}
    dissolved_paper_to_group = {}
    if different_work_groups:
        for group in different_work_groups:
            group_id = group.get("group_id") or f"dw-{len(dissolved_groups) + 1}"
            paper_ids = set(group.get("paper_ids") or [])
            dissolved_groups[group_id] = paper_ids
            for paper_id in paper_ids:
                dissolved_paper_to_group[paper_id] = group_id

    version_confirmed = {}
    version_confirmed_members = {}
    remaining_by_group = defaultdict(list)
    for index, record in enumerate(records):
        if index in grouped:
            continue
        group = version_map.get(record["paper_id"])
        if group and group.get("classification") == "confirmed_same_work":
            remaining_by_group[group.get("group_id")].append(index)

    for group_id, indices in remaining_by_group.items():
        if len(indices) < 2:
            continue
        representative_id = version_map[records[indices[0]]["paper_id"]].get("representative_id")
        representative = None
        for index in indices:
            if records[index]["paper_id"] == representative_id:
                representative = index
                break
        if representative is None:
            representative = indices[0]
        for index in indices:
            version_confirmed[index] = representative
        version_confirmed_members[representative] = [records[index]["paper_id"] for index in indices]

    version_suspected = {}
    for index, record in enumerate(records):
        if index in grouped or index in version_confirmed:
            continue
        group = version_map.get(record["paper_id"])
        if group and group.get("classification") == "suspected_same_work":
            version_suspected[index] = group.get("group_id")

    title_index = defaultdict(list)
    for index, record in enumerate(records):
        if index in grouped or index in version_confirmed or index in version_suspected:
            continue
        if record["normalized_title"]:
            title_index[record["normalized_title"]].append(index)

    suspected = {}
    suspected_counter = 0
    for title, indices in title_index.items():
        if len(indices) < 2:
            continue
        active_indices = []
        for index in indices:
            group_id = dissolved_paper_to_group.get(records[index]["paper_id"])
            dissolved_with = None
            if group_id:
                others = dissolved_groups[group_id] - {records[index]["paper_id"]}
                for other_index in indices:
                    if records[other_index]["paper_id"] in others:
                        dissolved_with = other_index
                        break
            if dissolved_with is None:
                active_indices.append(index)
        if len(active_indices) < 2:
            continue
        suspected_counter += 1
        group_id = f"suspected-{suspected_counter}"
        for index in active_indices:
            suspected[index] = group_id

    entries = []
    emitted = set()
    for index, record in enumerate(records):
        if index in grouped:
            first = grouped[index]
            if first in emitted:
                continue
            emitted.add(first)
            entry = dict(records[first])
            entry["duplicate_kind"] = (
                "same_doi" if records[first]["doi_norm"] else "same_openalex_id"
            )
            entry["member_ids"] = group_members[first]
            entries.append(entry)
            continue

        if index in version_confirmed:
            representative = version_confirmed[index]
            if representative in emitted:
                continue
            emitted.add(representative)
            entry = dict(records[representative])
            entry["duplicate_kind"] = "confirmed_same_work"
            entry["member_ids"] = version_confirmed_members[representative]
            entry["version_group_id"] = version_map[records[representative]["paper_id"]].get("group_id")
            entries.append(entry)
            continue

        entry = dict(record)
        if index in version_suspected:
            entry["duplicate_kind"] = "suspected_same_work"
            entry["version_group_id"] = version_suspected[index]
        elif index in suspected:
            entry["duplicate_kind"] = "suspected_duplicate"
            entry["suspected_group_id"] = suspected[index]
        else:
            entry["duplicate_kind"] = "none"
        entries.append(entry)

    return entries


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="在 SQLite FTS5 索引中检索论文。")
    parser.add_argument("query", help="检索词")
    parser.add_argument("--advanced", action="store_true",
                        help="高级模式：使用 FTS5 短语、前缀和布尔语法")
    parser.add_argument("--db", default="data/papers.db",
                        help="SQLite 数据库路径，默认 data/papers.db")
    parser.add_argument("--corpus", default="data/corpus.json",
                        help="候选语料 JSON（读取版本组信息），默认 data/corpus.json")
    parser.add_argument("--limit", type=int, default=10,
                        help="最多返回条数，默认 10")
    return parser.parse_args(argv)


def load_group_info(corpus_path):
    path = Path(corpus_path)
    if not path.exists():
        return None, []
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups = payload.get("version_groups") if isinstance(payload, dict) else []
    different = payload.get("different_work_groups") if isinstance(payload, dict) else []
    version_groups = groups if isinstance(groups, list) else None
    different_work_groups = different if isinstance(different, list) else []
    return version_groups, different_work_groups


def main(argv=None):
    args = parse_args(argv)
    if not Path(args.db).exists():
        raise SystemExit(f"未找到 {args.db}，请先运行 `python scripts/build_db.py`。")

    try:
        rows = search(args.db, args.query, args.limit, args.advanced)
    except ValueError as exc:
        raise SystemExit(str(exc))

    if not rows:
        print("没有匹配结果。")
        return

    version_groups, different_work_groups = load_group_info(args.corpus)
    for entry in group_results(rows, version_groups, different_work_groups):
        print(f"- {entry['title'] or '(无标题)'} ({entry['year']})")
        print(f"  来源: {entry['venue'] or '未知'} | DOI: {entry['doi'] or '无'} | 被引: {entry['cited_by_count'] or 0}")
        if entry.get("duplicate_kind") == "same_doi":
            print(f"  同一作品（DOI 相同），共 {len(entry['member_ids'])} 条记录：{', '.join(entry['member_ids'])}")
        elif entry.get("duplicate_kind") == "same_openalex_id":
            print(f"  同一作品（OpenAlex ID 相同），共 {len(entry['member_ids'])} 条记录：{', '.join(entry['member_ids'])}")
        elif entry.get("duplicate_kind") == "confirmed_same_work":
            print(f"  同一作品的不同版本（{entry['version_group_id']}），共 {len(entry['member_ids'])} 条记录：{', '.join(entry['member_ids'])}")
        elif entry.get("duplicate_kind") == "suspected_same_work":
            print(f"  疑似同一作品的不同版本（{entry['version_group_id']}），保留待核验")
        elif entry.get("duplicate_kind") == "suspected_duplicate":
            print(f"  疑似重复（标题相同但 DOI 不同，未合并）：{entry['suspected_group_id']}")
        if entry["snippet"]:
            print(f"  摘要片段: {entry['snippet']}")
        print(f"  相关度 rank: {entry['score']:.2f}\n")


if __name__ == "__main__":
    main()
