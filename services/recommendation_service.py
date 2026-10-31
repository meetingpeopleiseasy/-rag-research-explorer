import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "for", "on", "with",
    "at", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "we", "our", "their", "this", "that", "these", "those", "using", "based",
}

_INDEX = None


def _tokenize(text):
    return [token for token in re.findall(r"[a-z0-9]+", (text or "").lower()) if token not in STOPWORDS]


def _token_count(text):
    return len(_tokenize(text))


def _tfidf_vector(tokens, df, n_docs):
    counts = Counter(tokens)
    vector = {}
    for term, count in counts.items():
        idf = math.log((n_docs + 1) / (df.get(term, 0) + 1)) + 1
        vector[term] = (count / len(tokens)) * idf
    norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
    return {term: value / norm for term, value in vector.items()}


def _cosine(left, right):
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(term, 0.0) for term, value in left.items())


def _author_tokens(authors):
    tokens = set()
    for name in authors or []:
        if isinstance(name, str):
            tokens.update(re.findall(r"[a-z0-9]+", name.lower().replace(",", " ")))
    return tokens


def _jaccard(left, right):
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    union = len(left | right)
    return intersection / union if union else 0.0


def _load_screened_status(screened_path):
    path = Path(screened_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    papers = payload.get("papers") if isinstance(payload, dict) else payload
    if not isinstance(papers, list):
        return {}
    status = {}
    doc_types = {}
    for paper in papers:
        if isinstance(paper, dict) and paper.get("paperId"):
            paper_id = paper["paperId"]
            status[paper_id] = paper.get("relevance_status", "pending")
            doc_types[paper_id] = paper.get("doc_type")
    return status, doc_types


def _load_corpus(corpus_path):
    path = Path(corpus_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _get_index(db_path, corpus_path, screened_path):
    global _INDEX
    if _INDEX is not None and _INDEX["db_path"] == db_path:
        return _INDEX

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT paper_id, title, abstract, authors_json, year, venue, doi, cited_by_count "
            "FROM papers"
        ).fetchall()
    finally:
        conn.close()

    papers = []
    for row in rows:
        item = dict(row)
        item["authors"] = json.loads(item.get("authors_json") or "[]")
        papers.append(item)

    title_df = Counter()
    abstract_df = Counter()
    for paper in papers:
        title_df.update(set(_tokenize(paper.get("title"))))
        abstract_df.update(set(_tokenize(paper.get("abstract"))))

    title_vectors = [_tfidf_vector(_tokenize(p.get("title")), title_df, len(papers)) for p in papers]
    abstract_vectors = [_tfidf_vector(_tokenize(p.get("abstract")), abstract_df, len(papers)) for p in papers]

    by_id = {paper["paper_id"]: paper for paper in papers}
    id_to_idx = {paper["paper_id"]: index for index, paper in enumerate(papers)}

    corpus = _load_corpus(corpus_path)
    version_by_paper = {}
    confirmed_members = {}
    for group in corpus.get("version_groups") or []:
        classification = group.get("classification")
        group_id = group.get("group_id")
        member_ids = group.get("paper_ids") or []
        for paper_id in member_ids:
            version_by_paper[paper_id] = {
                "group_id": group_id,
                "classification": classification,
                "representative_id": group.get("representative_id"),
            }
        if classification == "confirmed_same_work":
            members = set(member_ids)
            for paper_id in member_ids:
                confirmed_members[paper_id] = members

    status, doc_types = _load_screened_status(screened_path)
    for paper in papers:
        paper["relevance_status"] = status.get(paper["paper_id"], paper.get("relevance_status", "pending"))
        paper["record_type"] = doc_types.get(paper["paper_id"])

    _INDEX = {
        "db_path": db_path,
        "papers": papers,
        "by_id": by_id,
        "id_to_idx": id_to_idx,
        "title_vectors": title_vectors,
        "abstract_vectors": abstract_vectors,
        "version_by_paper": version_by_paper,
        "confirmed_members": confirmed_members,
    }
    return _INDEX


def _recommendation_reasons(title_sim, abstract_sim, author_overlap):
    reasons = []
    if title_sim >= 0.15:
        reasons.append("Similar title terms")
    if abstract_sim >= 0.15:
        reasons.append("Similar abstract content")
    if author_overlap > 0:
        reasons.append("Shared authors")
    return reasons


def related_papers(
    db_path,
    corpus_path,
    screened_path,
    seed_id,
    limit=20,
    include_excluded=False,
    ranking="combined",
):
    index = _get_index(db_path, corpus_path, screened_path)
    if seed_id not in index["by_id"]:
        return None

    seed = index["by_id"][seed_id]
    seed_idx = index["id_to_idx"][seed_id]
    seed_title_vec = index["title_vectors"][seed_idx]
    seed_abstract_vec = index["abstract_vectors"][seed_idx]
    seed_author_tokens = _author_tokens(seed.get("authors"))
    seed_confirmed = index["confirmed_members"].get(seed_id, set())

    priority = {"included": 0, "pending": 1, "uncertain": 2, "excluded": 3}
    results = []
    for position, paper in enumerate(index["papers"]):
        paper_id = paper["paper_id"]
        if paper_id == seed_id or paper_id in seed_confirmed:
            continue
        status = paper.get("relevance_status", "pending")
        if status == "excluded" and not include_excluded:
            continue

        title_valid = _token_count(seed.get("title")) >= 2 and _token_count(paper.get("title")) >= 2
        abstract_valid = bool(_tokenize(seed.get("abstract"))) and bool(_tokenize(paper.get("abstract")))
        title_sim = _cosine(seed_title_vec, index["title_vectors"][position]) if title_valid else 0.0
        abstract_sim = _cosine(seed_abstract_vec, index["abstract_vectors"][position]) if abstract_valid else 0.0
        author_overlap = _jaccard(seed_author_tokens, _author_tokens(paper.get("authors")))
        combined = 0.5 * title_sim + 0.5 * abstract_sim

        results.append(
            {
                "paper_id": paper_id,
                "title": paper.get("title"),
                "authors": paper.get("authors"),
                "year": paper.get("year"),
                "venue": paper.get("venue"),
                "doi": paper.get("doi"),
                "abstract": paper.get("abstract"),
                "relevance_status": status,
                "record_type": paper.get("record_type"),
                "title_similarity": round(title_sim, 4),
                "abstract_similarity": round(abstract_sim, 4),
                "author_overlap": round(author_overlap, 4),
                "combined_score": round(combined, 4),
                "recommendation_reasons": _recommendation_reasons(title_sim, abstract_sim, author_overlap),
                "version_information": index["version_by_paper"].get(paper_id),
            }
        )

    # Confirmed versions of the same work should be represented once.
    version_groups = defaultdict(list)
    for item in results:
        version = item.get("version_information") or {}
        if version.get("classification") == "confirmed_same_work":
            version_groups[version.get("group_id")].append(item)
    keep = set()
    for group_id, members in version_groups.items():
        representative_id = members[0].get("version_information", {}).get("representative_id")
        representative = next(
            (member for member in members if member["paper_id"] == representative_id),
            members[0],
        )
        keep.add(representative["paper_id"])
    results = [
        item
        for item in results
        if (item.get("version_information") or {}).get("classification") != "confirmed_same_work"
        or item["paper_id"] in keep
    ]

    if ranking == "title":
        score_key = lambda item: -item["title_similarity"]
    elif ranking == "abstract":
        score_key = lambda item: -item["abstract_similarity"]
    else:
        score_key = lambda item: -item["combined_score"]
    results.sort(
        key=lambda item: (
            priority.get(item["relevance_status"], 2),
            score_key(item),
            -item["author_overlap"],
            item["paper_id"],
        )
    )
    return {
        "seed_paper": seed,
        "total": len(results),
        "related_papers": results[:limit],
    }
