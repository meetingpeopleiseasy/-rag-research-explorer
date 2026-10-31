#!/usr/bin/env python3
"""Export BM25 Top-10 results for manual relevance annotation and evaluate them."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import search_papers


def load_queries(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} 中应当是查询列表")
    return payload


def run_query(db_path, query_text, k=10):
    rows = search_papers.search(db_path, query_text, limit=k)
    results = []
    for rank, row in enumerate(rows, start=1):
        paper_id, title, year, venue, doi, cited_by_count, snippet, score, normalized_title = row
        results.append(
            {
                "rank": rank,
                "paper_id": paper_id,
                "title": title,
                "year": year,
                "venue": venue,
                "doi": doi,
                "bm25_score": score,
            }
        )
    return results


def compute_precision(results, annotations, k, relevant_pred):
    """Precision@k over judged results only.

    Returns (precision, judged_count). Unannotated results are excluded from
    both numerator and denominator; an empty judged set returns (None, 0).
    """
    top = results[:k]
    judged = [item for item in top if item["paper_id"] in annotations]
    if not judged:
        return None, 0
    relevant = sum(1 for item in judged if relevant_pred(annotations[item["paper_id"]]))
    return relevant / len(judged), len(judged)


def count_tie_groups(results, epsilon=1e-6):
    """Count adjacent pairs whose BM25 scores are (nearly) identical."""
    scores = [item["bm25_score"] for item in results if item.get("bm25_score") is not None]
    return sum(
        1
        for left, right in zip(scores, scores[1:])
        if abs(left - right) <= epsilon
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="导出每个查询的 BM25 Top-10 并计算已标注查询的指标。")
    parser.add_argument("--queries", default="eval/queries.json",
                        help="评测查询集，默认 eval/queries.json")
    parser.add_argument("--db", default="data/papers.db",
                        help="SQLite 数据库路径，默认 data/papers.db")
    parser.add_argument("--out", default="eval/results_top10.json",
                        help="导出结果路径，默认 eval/results_top10.json")
    parser.add_argument("--k", type=int, default=10,
                        help="每个查询导出的条数，默认 10")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not Path(args.db).exists():
        raise SystemExit(f"未找到 {args.db}，请先运行 `python scripts/build_db.py`。")

    queries = load_queries(args.queries)
    exported = []
    metrics = {}
    annotated_count = 0

    for query in queries:
        results = run_query(args.db, query["query"], args.k)
        annotations = query.get("annotations") or {}
        strict5, judged5 = compute_precision(results, annotations, 5, lambda v: v == 2)
        loose5, _ = compute_precision(results, annotations, 5, lambda v: v >= 1)
        strict10, judged10 = compute_precision(results, annotations, 10, lambda v: v == 2)
        loose10, _ = compute_precision(results, annotations, 10, lambda v: v >= 1)
        ties = count_tie_groups(results)
        matched_annotations = sum(
            1 for item in results[: args.k] if item["paper_id"] in annotations
        )
        annotated_count += 1 if matched_annotations else 0

        metrics[query["query_id"]] = {
            "annotated": bool(annotations),
            "annotations_count": len(annotations),
            "matched_annotations": matched_annotations,
            "judged_at_5": judged5,
            "judged_at_10": judged10,
            "precision_at_5": loose5,
            "precision_at_10": loose10,
            "precision_at_5_strict": strict5,
            "precision_at_10_strict": strict10,
            "precision_at_5_loose": loose5,
            "precision_at_10_loose": loose10,
            "tie_groups": ties,
        }
        exported.append(
            {
                "query_id": query["query_id"],
                "query": query["query"],
                "intent": query.get("intent"),
                "theme": query.get("theme"),
                "results": results,
            }
        )

        fmt = lambda value: f"{value:.3f}" if value is not None else "--"
        print(
            f"{query['query_id']} 标注={len(annotations)} 匹配Top10={matched_annotations} "
            f"P@5严格={fmt(strict5)} P@5宽松={fmt(loose5)} "
            f"P@10严格={fmt(strict10)} P@10宽松={fmt(loose10)} 同分组={ties}"
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db": str(Path(args.db)),
        "k": args.k,
        "queries": exported,
        "metrics": metrics,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n共 {len(queries)} 个查询，其中 {annotated_count} 个查询的标注实际匹配到 Top-{args.k}。")
    print(f"导出结果已写入 {out_path}")


if __name__ == "__main__":
    main()
