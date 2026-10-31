#!/usr/bin/env python3
"""Evaluate the TF-IDF recommendation variants against a manual judgment set."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import recommendation_service, search_service  # noqa: E402


def precision_at_k(results, annotations, k, relevant_pred):
    top = results[:k]
    judged = [item for item in top if item["paper_id"] in annotations]
    if not judged:
        return None, 0
    relevant = sum(1 for item in judged if relevant_pred(annotations[item["paper_id"]]))
    return relevant / len(judged), len(judged)


def metric(results, annotations):
    strict5, judged5 = precision_at_k(results, annotations, 5, lambda v: v == 2)
    loose5, _ = precision_at_k(results, annotations, 5, lambda v: v >= 1)
    strict10, judged10 = precision_at_k(results, annotations, 10, lambda v: v == 2)
    loose10, _ = precision_at_k(results, annotations, 10, lambda v: v >= 1)
    return {
        "judged_at_5": judged5,
        "judged_at_10": judged10,
        "precision_at_5_strict": strict5,
        "precision_at_10_strict": strict10,
        "precision_at_5_loose": loose5,
        "precision_at_10_loose": loose10,
    }


def run_seed(db_path, corpus_path, screened_path, seed):
    seed_id = seed["seed_id"]
    annotations = seed.get("annotations") or {}
    variants = {
        "title_only": recommendation_service.related_papers(
            db_path, corpus_path, screened_path, seed_id, limit=50, ranking="title"
        ),
        "abstract_only": recommendation_service.related_papers(
            db_path, corpus_path, screened_path, seed_id, limit=50, ranking="abstract"
        ),
        "combined": recommendation_service.related_papers(
            db_path, corpus_path, screened_path, seed_id, limit=50, ranking="combined"
        ),
    }
    bm25 = search_service.search_documents(
        db_path, corpus_path, seed["seed_title"], page=1, per_page=50,
        screened_path=screened_path,
    )

    systems = {}
    for name, result in variants.items():
        if result is None:
            systems[name] = {"results": [], "metrics": None}
            continue
        systems[name] = {
            "results": [
                {
                    "paper_id": item["paper_id"],
                    "title": item["title"],
                    "combined_score": item.get("combined_score"),
                    "title_similarity": item.get("title_similarity"),
                    "abstract_similarity": item.get("abstract_similarity"),
                }
                for item in result["related_papers"]
            ],
            "metrics": metric(result["related_papers"], annotations),
        }
    systems["bm25"] = {
        "results": [
            {"paper_id": item["paper_id"], "title": item["title"], "bm25_score": item.get("score")}
            for item in bm25["results"]
        ],
        "metrics": metric(bm25["results"], annotations),
    }
    return {"seed_id": seed_id, "topic": seed.get("topic"), "systems": systems}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="评估 TF-IDF 推荐变体与 BM25 baseline。")
    parser.add_argument("--seeds", default="eval/seed_papers.json")
    parser.add_argument("--db", default="data/papers.db")
    parser.add_argument("--corpus", default="data/corpus.json")
    parser.add_argument("--screened", default="data/screened_corpus.json")
    parser.add_argument("--out", default="eval/recommendation_results.json")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    seeds = json.loads(Path(args.seeds).read_text(encoding="utf-8"))
    output = []
    annotated = 0
    for seed in seeds:
        if seed.get("annotations"):
            annotated += 1
        output.append(run_seed(args.db, args.corpus, args.screened, seed))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seeds": output,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已评估 {len(seeds)} 个种子论文，其中 {annotated} 个有人工标注。")
    if annotated == 0:
        print("尚无人工标注，未计算 Precision@5/10；请先对 eval/recommendation_results.json 的候选池进行标注。")
    print(f"结果已写入 {out_path}")


if __name__ == "__main__":
    main()
