#!/usr/bin/env python3
"""Fetch RAG-related papers from the OpenAlex API.

Behaviour is aligned with the official OpenAlex documentation (checked
2026-10-28):
  - Endpoint: GET https://api.openalex.org/works
  - Auth: optional `Authorization: Bearer <key>` header (or `api_key=` param)
  - Params: filter=publication_year:<range>, search=<query>, select=<fields>,
    per-page (<= 100), page (1-based basic paging, up to 10,000 results)
  - OpenAlex does not ship plaintext abstracts; the `abstract_inverted_index`
    field is reconstructed into plain text.

The API key is read from the OPENALEX_API_KEY environment variable. If
python-dotenv is installed, the project-level .env is also loaded.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("缺少依赖 requests，请先运行 `pip install requests`。")

try:  # Optional convenience: load .env when python-dotenv is available.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from corpus import merge_unique


WORKS_URL = "https://api.openalex.org/works"
PAGE_SIZE = 100          # OpenAlex per-page maximum.
MAX_PAGES = 100          # Basic paging limit: 10,000 results.
MAX_RESULTS = PAGE_SIZE * MAX_PAGES

SELECT_FIELDS = (
    "id,doi,title,publication_year,publication_date,abstract_inverted_index,"
    "authorships,cited_by_count,primary_location,biblio,type,language"
)

DEFAULT_QUERY = "retrieval augmented generation"
DEFAULT_YEAR = "2021-2026"

# 候选检索策略（不是最终纳入标准）：按年份集中配置，便于统一调整。
QUERY_STRATEGY = {
    "2021": ["RAG", "retrieval-augmented language model"],
    "2022": ["retrieval-augmented generation", "knowledge-intensive NLP"],
    "2023": ["RAG", "retrieval-augmented language models"],
    "2024": ["RAG", "retrieval-augmented generation", "RAG evaluation"],
    "2025": ["RAG", "retrieval-augmented generation", "RAG evaluation"],
    "2026": ["RAG", "retrieval-augmented generation", "RAG evaluation"],
}


def get_api_key():
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    return key or None


def reconstruct_abstract(inverted_index):
    """Reconstruct plaintext from OpenAlex's abstract_inverted_index."""
    if not isinstance(inverted_index, dict) or not inverted_index:
        return None
    ordered = []
    for word, positions in inverted_index.items():
        for position in positions:
            ordered.append((position, word))
    if not ordered:
        return None
    ordered.sort(key=lambda item: item[0])
    return " ".join(word for _, word in ordered)


def normalize_work(work, query=None, year=None, run_id=None):
    """Map an OpenAlex work to the canonical record shape used downstream."""
    doi = work.get("doi")
    authors = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if isinstance(name, str) and name.strip():
            authors.append(name)

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    venue = source.get("display_name")
    external_ids = {"DOI": doi} if isinstance(doi, str) and doi.strip() else {}

    return {
        "paperId": work.get("id"),
        "title": work.get("title"),
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
        "year": work.get("publication_year"),
        "publicationDate": work.get("publication_date"),
        "doi": doi,
        "externalIds": external_ids,
        "source": "openalex",
        "authors": authors,
        "citedByCount": work.get("cited_by_count"),
        "type": work.get("type"),
        "language": work.get("language"),
        "venue": venue,
        "biblio": work.get("biblio"),
        "matched_queries": [query] if query else [],
        "matched_years": [year] if year else [],
        "run_id": run_id,
    }


def normalize_doi(record):
    external_ids = record.get("externalIds")
    if not isinstance(external_ids, dict):
        return None
    doi = external_ids.get("DOI")
    if isinstance(doi, str) and doi.strip():
        return doi.strip().lower()
    return None


def retry_after_seconds(response):
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return None


def request_page(session, params, headers, max_retries):
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = session.get(WORKS_URL, params=params, headers=headers, timeout=(10, 30))
        except requests.RequestException as exc:
            last_error = exc
            if attempt < max_retries:
                wait = min(60, 2 ** attempt)
                print(f"  网络错误（第 {attempt + 1}/{max_retries + 1} 次）：{exc}，{wait}s 后重试", file=sys.stderr)
                time.sleep(wait)
                continue
            break

        status = response.status_code
        if status == 200:
            try:
                return response.json()
            except ValueError as exc:
                raise RuntimeError(f"OpenAlex API 返回了非 JSON 响应：{response.text[:300]}") from exc

        if status == 429:
            wait = retry_after_seconds(response)
            if wait is None:
                wait = min(60, 2 ** attempt)
            retry_hint = f"，{wait}s 后重试" if attempt < max_retries else ""
            message = f"  HTTP 429 被限流（第 {attempt + 1}/{max_retries + 1} 次）{retry_hint}"
        elif status >= 500:
            wait = min(60, 2 ** attempt)
            retry_hint = f"，{wait}s 后重试" if attempt < max_retries else ""
            message = f"  HTTP {status} 服务端错误（第 {attempt + 1}/{max_retries + 1} 次）{retry_hint}"
        else:
            raise RuntimeError(
                f"OpenAlex API 返回 HTTP {status}：{response.text[:300]}"
            )

        print(message, file=sys.stderr)
        if attempt < max_retries:
            time.sleep(wait)
        else:
            last_error = RuntimeError(f"HTTP {status}：{response.text[:300]}")

    raise RuntimeError(f"请求失败（重试 {max_retries} 次后仍失败）：{last_error}")


def collect_query(session, query, year, limit, headers, max_retries, interval, raw_dir, run_id, first_page):
    """Fetch all pages for one (query, year) pair; returns (records, raw_pages)."""
    records = []
    raw_pages = 0
    per_page = min(PAGE_SIZE, limit)
    page = 1

    while len(records) < limit:
        params = {
            "filter": f"publication_year:{year}",
            "search": query,
            "select": SELECT_FIELDS,
            "per-page": per_page,
            "page": page,
        }
        payload = request_page(session, params, headers, max_retries)

        raw_pages += 1
        page_index = first_page + raw_pages
        raw_path = raw_dir / f"papers_run_{run_id}_page_{page_index:03d}.json"
        raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise RuntimeError(f"响应结构异常：{str(payload)[:300]}")

        if raw_pages == 1:
            meta = payload.get("meta") or {}
            total = meta.get("count")
            if total is not None:
                print(f"查询 `{query}`（year={year}）匹配总数：{total}")

        results = payload["results"]
        if not results:
            break

        for work in results:
            if not isinstance(work, dict):
                continue
            records.append(normalize_work(work, query=query, year=year, run_id=run_id))
            if len(records) >= limit:
                break

        if len(results) < per_page:
            break
        page += 1
        if page > MAX_PAGES:
            break
        if len(records) < limit:
            time.sleep(interval)

    return records, raw_pages


def accumulate_run(records):
    """Merge records within one run by OpenAlex ID / DOI, union matched fields."""
    papers = []
    id_index = {}
    doi_index = {}
    duplicates = 0

    for record in records:
        paper_id = record.get("paperId")
        doi = normalize_doi(record)
        target = None
        if paper_id and paper_id in id_index:
            target = id_index[paper_id]
        elif doi and doi in doi_index:
            target = doi_index[doi]

        if target is None:
            if paper_id:
                id_index[paper_id] = len(papers)
            if doi:
                doi_index.setdefault(doi, len(papers))
            papers.append(record)
            continue

        existing = papers[target]
        existing["matched_queries"] = merge_unique(
            existing.get("matched_queries"), record.get("matched_queries")
        )
        existing["matched_years"] = merge_unique(
            existing.get("matched_years"), record.get("matched_years")
        )
        duplicates += 1

    return papers, duplicates


def run_batch(entries, limit, out_dir, interval, max_retries):
    api_key = get_api_key()
    if api_key is None:
        print(
            "警告：未检测到 OPENALEX_API_KEY，将使用匿名共享配额（每日 $0.10 共享预算，10 req/s）。"
            "建议在 https://openalex.org/settings/api 申请免费 Key 并写入 .env。",
            file=sys.stderr,
        )

    out_dir = Path(out_dir)
    raw_dir = out_dir / "raw"
    runs_dir = out_dir / "runs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fetched_at = datetime.now(timezone.utc).isoformat()

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    session = requests.Session()
    all_records = []
    raw_pages_total = 0
    first_page = 0

    for entry in entries:
        records, pages = collect_query(
            session, entry["query"], entry["year"], limit, headers,
            max_retries, interval, raw_dir, run_id, first_page,
        )
        all_records.extend(records)
        raw_pages_total += pages
        first_page += pages

    papers, duplicates = accumulate_run(all_records)
    run_record = {
        "meta": {
            "run_id": run_id,
            "fetched_at": fetched_at,
            "source": WORKS_URL,
            "strategy": entries,
            "limit_per_query": limit,
            "raw_records": len(all_records),
            "unique_papers": len(papers),
            "duplicates_merged_in_run": duplicates,
            "raw_pages": raw_pages_total,
        },
        "papers": papers,
    }
    run_path = runs_dir / f"run_{run_id}.json"
    run_path.write_text(json.dumps(run_record, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已保存本轮 {len(papers)} 篇去重后论文到 {run_path}")
    print(f"已保存 {raw_pages_total} 页原始响应到 {raw_dir}/")
    print(f"本轮内部合并重复记录：{duplicates}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="从 OpenAlex API 批量获取 2021–2026 年 RAG 相关论文。"
    )
    parser.add_argument("--strategy", action="store_true",
                        help="按内置 QUERY_STRATEGY 按年份、多查询词批量采集")
    parser.add_argument("--query", default=None,
                        help="单个查询词（不使用 --strategy 时生效，默认 retrieval augmented generation）")
    parser.add_argument("--year", default=None,
                        help="单个年份/范围（不使用 --strategy 时生效，默认 2021-2026）")
    parser.add_argument("--limit", type=int, default=100,
                        help="每个查询的抓取上限，默认 100，最大 10000")
    parser.add_argument("--out-dir", default="data",
                        help="输出目录，默认 data")
    parser.add_argument("--interval", type=float, default=1.2,
                        help="分页请求之间的间隔秒数，默认 1.2")
    parser.add_argument("--max-retries", type=int, default=4,
                        help="429/5xx 等可重试错误的最大重试次数，默认 4")
    return parser.parse_args(argv)


def strategy_entries():
    entries = []
    for year in sorted(QUERY_STRATEGY):
        for query in QUERY_STRATEGY[year]:
            entries.append({"year": str(year), "query": query})
    return entries


def main(argv=None):
    args = parse_args(argv)
    if args.limit <= 0:
        sys.exit("--limit 必须为正整数。")
    if args.limit > MAX_RESULTS:
        print(f"注意：OpenAlex 基础分页最多返回 {MAX_RESULTS} 条，已把 --limit 调整为 {MAX_RESULTS}。")
        args.limit = MAX_RESULTS

    if args.strategy:
        entries = strategy_entries()
    else:
        entries = [{"year": args.year or DEFAULT_YEAR, "query": args.query or DEFAULT_QUERY}]

    try:
        run_batch(entries, args.limit, args.out_dir, args.interval, args.max_retries)
    except RuntimeError as exc:
        sys.exit(f"抓取失败：{exc}")


if __name__ == "__main__":
    main()
