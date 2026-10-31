#!/usr/bin/env python3
"""Screen the candidate corpus for relevance without modifying raw records."""

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


RULE_VERSION = "v1"

RULE_PATTERNS = {
    "full_rag_term": re.compile(
        r"retrieval[- ]augmented(?:\s+generation)?|retrieval augmented generation",
        re.IGNORECASE,
    ),
    "rag_abbrev": re.compile(r"\bRAG\b"),
    "non_rag_meaning": re.compile(
        r"\brag[\s-]?(?:doll|time|a|paper|trade|rug|quilt|bag|picker|man|woman)\b",
        re.IGNORECASE,
    ),
}

JOURNAL_TYPES = {"article"}
CONFERENCE_TYPES = {"conference-paper", "conference-abstract"}
PREPRINT_TYPES = {"preprint"}
REVIEW_TYPES = {"review"}
SOFTWARE_DATASET_TYPES = {"dataset", "software", "software-paper"}

CONFERENCE_VENUE_KEYWORDS = (
    "conference", "proceedings", "sigir", "acl", "emnlp", "naacl", "neurips",
    "icml", "iclr", "aaai", "iccv", "cvpr", "coling", "symposium", "workshop",
)


def classify_doc_type(paper):
    """Return a coarse document type; `unknown` when evidence is insufficient."""
    paper_type = (paper.get("type") or "").strip().lower()
    venue = (paper.get("venue") or "").lower()
    title = (paper.get("title") or "").lower()

    if paper_type in REVIEW_TYPES:
        return "review"
    if paper_type in SOFTWARE_DATASET_TYPES or any(
        key in title for key in ("software", "dataset", "r package", "github")
    ) or "zenodo" in venue:
        return "software_or_dataset"
    if paper_type in PREPRINT_TYPES or "arxiv" in venue or "ssrn" in venue:
        return "preprint"
    if paper_type in CONFERENCE_TYPES:
        return "conference_paper"
    if paper_type in JOURNAL_TYPES:
        if any(key in venue for key in CONFERENCE_VENUE_KEYWORDS):
            return "conference_paper"
        if venue and "journal" in venue or "transactions" in venue or "letters" in venue:
            return "journal_article"
        return "journal_article" if venue else "unknown"
    if not paper_type and any(key in venue for key in CONFERENCE_VENUE_KEYWORDS):
        return "conference_paper"
    return "unknown"


def screen_paper(paper, patterns=None):
    """Classify one paper; returns (status, reasons)."""
    patterns = patterns or RULE_PATTERNS
    title = paper.get("title") or ""
    abstract = paper.get("abstract") or ""
    abstract_missing = not abstract.strip()

    full_title = patterns["full_rag_term"].search(title) is not None
    full_abstract = patterns["full_rag_term"].search(abstract) is not None
    abbrev_title = patterns["rag_abbrev"].search(title) is not None
    abbrev_abstract = patterns["rag_abbrev"].search(abstract) is not None
    non_rag = (
        patterns["non_rag_meaning"].search(title) is not None
        or patterns["non_rag_meaning"].search(abstract) is not None
    )
    short_title = len(re.findall(r"[^\W_]+", title)) <= 1

    if non_rag and not full_title and not full_abstract:
        return "excluded", ["non_rag_meaning"]

    has_any_rag = full_title or full_abstract or abbrev_title or abbrev_abstract
    if not has_any_rag:
        if short_title:
            return "excluded", ["no_rag_signal", "short_title_ambiguous"]
        return "excluded", ["no_rag_signal"]

    if abstract_missing:
        return "uncertain", ["abstract_missing"]

    title_says_rag = full_title or abbrev_title
    abstract_says_rag = full_abstract or abbrev_abstract
    if title_says_rag != abstract_says_rag:
        return "uncertain", ["title_abstract_conflict"]

    if full_title or full_abstract:
        return "included", ["explicit_rag_term"]

    return "uncertain", ["abbreviation_only"]


def screen_papers(papers):
    screened = []
    for paper in papers:
        status, reasons = screen_paper(paper)
        item = dict(paper)
        item["relevance_status"] = status
        item["screening_reason"] = reasons
        item["doc_type"] = classify_doc_type(paper)
        item["screening_rule_version"] = RULE_VERSION
        screened.append(item)
    return screened


def build_report(screened):
    total = len(screened)
    status_counts = Counter(item["relevance_status"] for item in screened)
    doc_type_counts = Counter(item.get("doc_type") for item in screened)
    year_counts = Counter(item.get("year") for item in screened)
    missing_abstract = sum(
        1 for item in screened
        if not (isinstance(item.get("abstract"), str) and item.get("abstract").strip())
    )
    excluded_rule_counts = Counter()
    for item in screened:
        if item["relevance_status"] == "excluded":
            for reason in item.get("screening_reason", []):
                excluded_rule_counts[reason] += 1
    return {
        "total": total,
        "status_counts": dict(status_counts),
        "doc_type_counts": dict(doc_type_counts),
        "year_distribution": {str(year): count for year, count in sorted(year_counts.items()) if year is not None},
        "missing_year_count": year_counts.get(None, 0),
        "abstract_missing": missing_abstract,
        "abstract_missing_rate": (missing_abstract / total) if total else 0.0,
        "excluded_rule_counts": dict(excluded_rule_counts),
    }


def print_report(report):
    print(f"总记录数：{report['total']}")
    print("状态分布：" + ", ".join(f"{k}={v}" for k, v in sorted(report["status_counts"].items())))
    print("文献类型分布：" + ", ".join(f"{k}={v}" for k, v in sorted(report["doc_type_counts"].items())))
    print("年份分布：" + ", ".join(f"{k}={v}" for k, v in sorted(report["year_distribution"].items())))
    print(f"摘要缺失：{report['abstract_missing']}/{report['total']} = {report['abstract_missing_rate']:.1%}")
    if report["excluded_rule_counts"]:
        print("排除规则命中：" + ", ".join(f"{k}={v}" for k, v in sorted(report["excluded_rule_counts"].items())))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="对候选语料做相关性初筛。")
    parser.add_argument("--corpus", default="data/corpus.json",
                        help="候选语料 JSON，默认 data/corpus.json")
    parser.add_argument("--out", default="data/screened_corpus.json",
                        help="初筛结果输出路径，默认 data/screened_corpus.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印报告，不写输出文件")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    corpus_path = Path(args.corpus)
    out_path = Path(args.out)
    if not corpus_path.exists():
        raise SystemExit(f"未找到 {corpus_path}，请先运行 `python scripts/merge_corpus.py`。")
    if corpus_path.resolve() == out_path.resolve():
        raise SystemExit("--out 不能覆盖 --corpus，请使用独立的输出文件。")

    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    papers = payload.get("papers") if isinstance(payload, dict) else payload
    if not isinstance(papers, list):
        raise SystemExit(f"{corpus_path} 中没有 `papers` 列表。")

    screened = screen_papers(papers)
    report = build_report(screened)
    print_report(report)

    if args.dry_run:
        print("\n（dry-run：未写入文件）")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "rule_version": RULE_VERSION,
            "source_corpus": str(corpus_path),
            "report": report,
        },
        "papers": screened,
    }
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n初筛结果已写入 {out_path}")


if __name__ == "__main__":
    main()
