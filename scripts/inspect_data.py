#!/usr/bin/env python3
"""Inspect fetch runs and candidate corpus statistics."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import corpus


YEARS = [str(year) for year in range(2021, 2027)]


def load_run_records(runs_dir):
    files = sorted(Path(runs_dir).glob("run_*.json"))
    records = []
    run_count = 0
    raw_fetched = 0
    collection_duplicates = 0
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"警告：跳过无法解析的 run 文件 {path}（{exc}）", file=sys.stderr)
            continue
        run_count += 1
        meta = payload.get("meta") if isinstance(payload, dict) else {}
        raw_fetched += int(meta.get("raw_records") or 0)
        collection_duplicates += int(meta.get("duplicates_merged_in_run") or 0)
        papers = payload.get("papers") if isinstance(payload, dict) else payload
        if isinstance(papers, list):
            records.extend(item for item in papers if isinstance(item, dict))
    return records, run_count, raw_fetched, collection_duplicates


def unique_by_id(records):
    seen = set()
    unique = []
    for record in records:
        paper_id = record.get("paperId")
        if isinstance(paper_id, str) and paper_id.strip():
            if paper_id in seen:
                continue
            seen.add(paper_id)
        unique.append(record)
    return unique


def analyze(records, source_label, corpus_path=None, raw_fetched=0, collection_duplicates=0):
    total = len(records)
    duplicates = corpus.count_duplicates(records)
    unique = unique_by_id(records)

    years = Counter()
    missing_abstract = 0
    for record in unique:
        year = record.get("year")
        years[year if isinstance(year, int) else None] += 1
        abstract = record.get("abstract")
        if not (isinstance(abstract, str) and abstract.strip()):
            missing_abstract += 1

    print(f"数据来源：{source_label}")
    if raw_fetched:
        print(f"原始抓取记录数：{raw_fetched}")
        print(f"采集阶段移除重复记录：{collection_duplicates}")
    print(f"run 去重后记录数（合并输入）：{total}")
    print(f"OpenAlex ID 重复（多余记录）：{duplicates['duplicate_by_id']}")
    print(f"DOI 重复候选：{duplicates['duplicate_by_doi']}")
    print(f"规范化标题重复候选：{duplicates['duplicate_by_title']}")
    print(f"按 OpenAlex ID 去重后：{len(unique)}")

    print("\n年份覆盖（按 OpenAlex ID 去重后）：")
    for year in YEARS:
        print(f"  {year}: {years.get(int(year), 0)}")
    if years.get(None):
        print(f"  (缺失): {years[None]}")
    missing_years = [year for year in YEARS if years.get(int(year), 0) == 0]
    print(f"缺失年份：{', '.join(missing_years) if missing_years else '无'}")

    if unique:
        rate = missing_abstract / len(unique)
        print(f"\n摘要缺失（按 ID 去重后）：{missing_abstract}/{len(unique)} = {rate:.1%}")
    else:
        print("\n摘要缺失：0/0 = 0.0%")

    if corpus_path and Path(corpus_path).exists():
        payload = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
        papers = payload.get("papers") if isinstance(payload, dict) else []
        conflicts = payload.get("conflicts") if isinstance(payload, dict) else []
        title_duplicate_groups = payload.get("title_duplicate_groups") if isinstance(payload, dict) else []
        meta = payload.get("meta") if isinstance(payload, dict) else {}
        print(f"\n已合并候选语料：{corpus_path}")
        print(f"  候选论文：{len(papers) if isinstance(papers, list) else 0}")
        print(f"  合并阶段移除重复：{meta.get('merge_duplicates_removed', 0)}")
        print(f"  DOI 重复组：{meta.get('doi_duplicate_groups', 0)}")
        print(f"  标题重复合并组：{meta.get('title_duplicate_groups_merged', 0)}")
        print(f"  保留待核验标题重复组：{len(title_duplicate_groups) if isinstance(title_duplicate_groups, list) else 0}")
        print(f"  冲突组：{len(conflicts) if isinstance(conflicts, list) else 0}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="统计多轮抓取结果的重复、年份覆盖和摘要缺失率。"
    )
    parser.add_argument("--runs-dir", default="data/runs",
                        help="run 记录目录，默认 data/runs")
    parser.add_argument("--corpus", default="data/corpus.json",
                        help="候选语料 JSON，默认 data/corpus.json")
    parser.add_argument("--papers", default="data/papers.json",
                        help="旧版 papers.json 回退路径")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    runs_dir = Path(args.runs_dir)
    corpus_path = Path(args.corpus)

    if runs_dir.is_dir() and list(runs_dir.glob("run_*.json")):
        records, run_count, raw_fetched, collection_duplicates = load_run_records(runs_dir)
        analyze(
            records, f"{runs_dir}（{run_count} 个 run 文件）", corpus_path,
            raw_fetched=raw_fetched, collection_duplicates=collection_duplicates,
        )
        return

    if corpus_path.exists():
        payload = json.loads(corpus_path.read_text(encoding="utf-8"))
        papers = payload.get("papers") if isinstance(payload, dict) else payload
        if isinstance(papers, list):
            print(f"注意：{runs_dir} 中没有 run 文件，回退到去重后的 {corpus_path}。")
            analyze(papers, str(corpus_path), corpus_path)
            return

    papers_path = Path(args.papers)
    if papers_path.exists():
        payload = json.loads(papers_path.read_text(encoding="utf-8"))
        papers = payload.get("papers") if isinstance(payload, dict) else payload
        if isinstance(papers, list):
            print(f"注意：回退到旧版 {papers_path}。")
            analyze(papers, str(papers_path))
            return

    sys.exit(
        "未找到数据。请先运行 `python scripts/fetch_papers.py --strategy`，"
        f"预期在 {runs_dir}/ 下生成 run 文件。"
    )


if __name__ == "__main__":
    main()
