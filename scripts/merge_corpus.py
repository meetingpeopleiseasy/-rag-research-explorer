#!/usr/bin/env python3
"""Merge multiple fetch runs into a deduplicated candidate corpus."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import corpus


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
            print(f"警告：跳过无法解析的 run 文件 {path}（{exc}）")
            continue
        run_count += 1
        meta = payload.get("meta") if isinstance(payload, dict) else {}
        raw_fetched += int(meta.get("raw_records") or 0)
        collection_duplicates += int(meta.get("duplicates_merged_in_run") or 0)
        papers = payload.get("papers") if isinstance(payload, dict) else payload
        if isinstance(papers, list):
            records.extend(item for item in papers if isinstance(item, dict))
    return records, run_count, raw_fetched, collection_duplicates


def load_review_decisions(path):
    review_path = Path(path)
    if not review_path.exists():
        return {}
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    groups = payload.get("groups") if isinstance(payload, dict) else []
    decisions = {}
    for group in groups or []:
        group_id = group.get("group_id")
        decision = group.get("review_decision")
        if group_id and decision:
            decisions[group_id] = decision
    return decisions


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="合并多轮抓取结果，生成去重候选语料。")
    parser.add_argument("--runs-dir", default="data/runs",
                        help="run 记录目录，默认 data/runs")
    parser.add_argument("--out", default="data/corpus.json",
                        help="输出候选语料 JSON，默认 data/corpus.json")
    parser.add_argument("--review", default="data/version_review.json",
                        help="人工版本审核结果，默认 data/version_review.json")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_dir() or not list(runs_dir.glob("run_*.json")):
        raise SystemExit(
            f"未找到 run 文件（{runs_dir}/run_*.json），请先运行 "
            "`python scripts/fetch_papers.py --strategy`。"
        )

    records, run_count, raw_fetched, collection_duplicates = load_run_records(runs_dir)
    result = corpus.merge_records(records)
    papers = result["papers"]
    conflicts = result["conflicts"]
    title_duplicate_groups = result["title_duplicate_groups"]
    auto_version_groups = corpus.build_version_groups(papers)
    review_decisions = load_review_decisions(args.review)
    reviewed = corpus.apply_version_review(auto_version_groups, review_decisions)
    version_groups = reviewed["version_groups"]
    different_work_groups = reviewed["different_work_groups"]
    confirmed_versions = sum(
        1 for group in version_groups if group["classification"] == "confirmed_same_work"
    )
    suspected_versions = sum(
        1 for group in version_groups if group["classification"] == "suspected_same_work"
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_count": run_count,
            "raw_fetched_records": raw_fetched,
            "collection_duplicates_removed": collection_duplicates,
            "input_records": len(records),
            "candidate_papers": len(papers),
            "merge_duplicates_removed": len(records) - len(papers),
            "doi_duplicate_groups": result["doi_duplicate_groups"],
            "title_duplicate_groups_merged": result["title_duplicate_groups_merged"],
            "title_duplicate_groups_kept": len(title_duplicate_groups),
            "conflict_groups": len(conflicts),
            "version_groups": len(version_groups),
            "confirmed_version_groups": confirmed_versions,
            "suspected_version_groups": suspected_versions,
            "review_same_work": sum(1 for g in version_groups if g.get("review_decision") == "same_work"),
            "review_uncertain": sum(1 for g in version_groups if g.get("review_decision") == "uncertain"),
            "review_different_work": len(different_work_groups),
        },
        "papers": papers,
        "conflicts": conflicts,
        "title_duplicate_groups": title_duplicate_groups,
        "version_groups": version_groups,
        "different_work_groups": different_work_groups,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"原始抓取 {raw_fetched} 条，采集阶段移除重复 {collection_duplicates} 条；"
        f"合并输入 {len(records)} 条，输出候选论文 {len(papers)} 篇（合并移除 {len(records) - len(papers)} 条）。"
    )
    print(
        f"DOI 重复组 {result['doi_duplicate_groups']}，标题重复合并组 {result['title_duplicate_groups_merged']}，"
        f"保留待核验标题重复组 {len(title_duplicate_groups)}，冲突组 {len(conflicts)}。"
    )
    print(
        f"作品版本组 {len(version_groups)} 个：确认同一作品 {confirmed_versions} 个，"
        f"疑似同一作品 {suspected_versions} 个。"
    )
    print(
        f"人工审核回填：same_work {sum(1 for g in version_groups if g.get('review_decision') == 'same_work')} 个，"
        f"different_work {len(different_work_groups)} 个，"
        f"uncertain {sum(1 for g in version_groups if g.get('review_decision') == 'uncertain')} 个。"
    )
    print(f"已写入 {out_path}")


if __name__ == "__main__":
    main()
