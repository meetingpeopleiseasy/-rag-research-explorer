import json
import re
import sqlite3
from collections import Counter, defaultdict

from services import recommendation_service


STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "for", "on", "with",
    "at", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "this", "that", "these", "those", "our", "their", "its", "his", "her",
    "which", "what", "when", "where", "who", "whom", "how", "why", "can",
    "could", "may", "might", "shall", "should", "will", "would", "do", "does",
    "did", "has", "have", "had", "not", "no", "nor", "so", "than", "too",
    "very", "just", "also", "into", "over", "under", "between", "through",
    "during", "before", "after", "above", "below", "up", "down", "out", "off",
}

DOMAIN_SINGLE = STOPWORDS | {
    "however", "such", "results", "result", "framework", "data", "information",
    "knowledge", "systems", "system", "paper", "method", "methods", "approach",
    "study", "research", "using", "based", "large", "language", "model",
    "models", "retrieval", "augmented", "generation", "rag", "llm", "llms",
    "context", "performance", "analysis", "task", "tasks", "new", "novel",
    "towards", "toward", "effective", "efficient", "improved", "enhanced",
    "proposed", "propose", "show", "shows", "shown", "demonstrate",
    "demonstrates", "demonstrated", "improve", "improves", "improving",
    "significant", "various", "different", "recent", "existing", "several",
    "important", "crucial", "highlight", "highlights", "direction",
    "directions", "structured", "assessment", "evaluate", "evaluated",
    "developed", "develop", "develops", "efficiency", "emerging",
    "contextually", "need", "needs", "potential", "challenge", "challenges",
    "address", "addresses", "addressed", "explore", "explores", "explored",
    "focus", "focuses", "focused", "aim", "aims", "aimed", "present",
    "presents", "presented", "provide", "provides", "provided", "enables",
    "enable", "enabled", "reduces", "reduce", "reduced", "outperform",
    "outperforms", "better", "well", "key", "main", "mini", "agentic",
    "types", "type", "ensuring", "ensure", "ensures", "highlighting",
    "highlighted", "technology", "technologies", "analyzing", "analyzed",
    "analyse", "analyses", "analyze", "lack", "lacks",
    "consistently", "struggle", "final", "advancing", "application",
    "applications", "real", "internal", "leading", "three", "evaluating",
    "article", "effectively", "remain", "strengths",
}

PLACEHOLDER_AUTHORS = {"", "unknown", "null", "none", "n/a", "na"}
INSTITUTION_WORDS = {
    "university", "institute", "association", "laboratory", "lab", "college",
    "school", "department", "center", "centre", "corporation", "inc", "ltd",
}

RAG_PHRASE_WORDS = {
    "retrieval", "augmented", "generation", "rag", "multimodal", "graph",
    "knowledge", "intensive", "dense", "passage", "evaluation", "hallucination",
}
GENERIC_WORDS = DOMAIN_SINGLE - RAG_PHRASE_WORDS


def _words(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _load_screened(screened_path):
    try:
        with open(screened_path, encoding="utf-8") as fh:
            payload = json.loads(fh.read())
    except (OSError, json.JSONDecodeError):
        return {}
    papers = payload.get("papers") if isinstance(payload, dict) else payload
    if not isinstance(papers, list):
        return {}
    return {
        paper.get("paperId"): paper
        for paper in papers
        if isinstance(paper, dict) and paper.get("paperId")
    }


def _load_papers(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT paper_id, title, abstract, authors_json, year FROM papers"
        ).fetchall()
    finally:
        conn.close()
    papers = []
    for row in rows:
        paper = dict(row)
        paper["authors"] = json.loads(paper.get("authors_json") or "[]")
        papers.append(paper)
    return papers


def _normalize_author(name):
    if not isinstance(name, str):
        return None
    value = name.strip()
    lowered = value.lower()
    if lowered in PLACEHOLDER_AUTHORS:
        return None
    if ";" in value:
        value = value.split(";")[0].strip()
    if "id_orcid" in lowered or "orcid" in lowered:
        value = value.split(",")[0].strip()
    if "," in value:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        value = " ".join(reversed(parts))
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return None
    tokens = value.split()
    if any(token.lower() in INSTITUTION_WORDS for token in tokens):
        return None
    value = value.title()
    if len(value) > 60:
        value = value[:60].rstrip()
    return value


def _filter_papers(papers, screened, statuses):
    if statuses is None:
        return papers
    status_set = set(statuses)
    return [
        paper
        for paper in papers
        if (screened.get(paper["paper_id"]) or {}).get("relevance_status", "pending") in status_set
    ]


def _extract_topics(papers, limit=8):
    text_by_id = {}
    title_words = {}
    for paper in papers:
        paper_id = paper["paper_id"]
        words = _words(paper.get("title"))
        title_words[paper_id] = words
        text_by_id[paper_id] = " ".join(_words(paper.get("title")) + _words(paper.get("abstract")))

    phrase_papers = defaultdict(set)
    for paper in papers:
        words = title_words[paper["paper_id"]]
        for size in (2, 3):
            for index in range(len(words) - size + 1):
                gram = words[index:index + size]
                if any(len(word) < 2 for word in gram):
                    continue
                if any(word in STOPWORDS for word in gram):
                    continue
                if all(word in GENERIC_WORDS for word in gram):
                    continue
                phrase = " ".join(gram)
                phrase_papers[phrase].add(paper["paper_id"])

    counted = []
    for phrase, paper_ids in phrase_papers.items():
        count = sum(1 for text in text_by_id.values() if phrase in text)
        if count < 2:
            continue
        counted.append({"phrase": phrase, "term": phrase.title(), "papers": count, "size": len(phrase.split())})

    # Prefer longer phrases and suppress overlapping bigrams with similar counts.
    trigrams = {item["phrase"] for item in counted if item["size"] == 3}
    topics = []
    for item in counted:
        words = item["phrase"].split()
        if set(words) == {"retrieval", "augmented", "generation"} and item["phrase"] != "retrieval augmented generation":
            continue
        if "rag" in words and ("augmented" in words or "generation" in words) and item["phrase"] != "retrieval augmented generation":
            continue
        if item["size"] == 2:
            covered = any(
                words[0] in trigram and words[1] in trigram
                for trigram in trigrams
            )
            if covered:
                continue
        topics.append({"term": item["term"], "papers": item["papers"]})
    topics.sort(key=lambda item: (-item["papers"], item["term"]))
    return topics[:limit]


def get_home_stats(db_path, screened_path, topic_limit=8):
    papers = _load_papers(db_path)
    screened = _load_screened(screened_path)
    authors = set()
    doc_types = Counter()
    for paper in papers:
        paper["doc_type"] = (screened.get(paper["paper_id"]) or {}).get("doc_type")
        doc_types[paper.get("doc_type") or "unknown"] += 1
        for name in paper["authors"]:
            normalized = _normalize_author(name)
            if normalized:
                authors.add(normalized)

    included = _filter_papers(papers, screened, ["included"])
    years = [paper["year"] for paper in papers if isinstance(paper["year"], int)]
    return {
        "papers": len(papers),
        "authors": len(authors),
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
        "doc_types": dict(doc_types),
        "topics": _extract_topics(included, topic_limit),
        "note": "authors are counted by normalized name string; no ORCID-based identity resolution",
    }


def publication_trend(papers):
    trend = Counter()
    for paper in papers:
        if isinstance(paper.get("year"), int):
            trend[paper["year"]] += 1
    years = sorted(trend)
    return {
        "years": [str(year) for year in years],
        "counts": [trend[year] for year in years],
        "note": "counts reflect the current local candidate corpus, not the full RAG literature; 2026 may be incomplete",
    }


def top_authors(papers, limit=10):
    counts = Counter()
    for paper in papers:
        seen = set()
        for name in paper.get("authors") or []:
            normalized = _normalize_author(name)
            if normalized and normalized not in seen:
                counts[normalized] += 1
                seen.add(normalized)
    return {
        "authors": [{"author": name, "papers": count} for name, count in counts.most_common(limit)],
        "note": "name-based author counts; same-name authors are not identity-resolved without ORCID",
    }


def emerging_keywords(papers, early_start=2021, early_end=2023, late_start=2024, late_end=2025, limit=10):
    yearly = defaultdict(Counter)
    yearly_papers = Counter()
    for paper in papers:
        year = paper.get("year")
        if not isinstance(year, int):
            continue
        yearly_papers[year] += 1
        for word in set(_words(paper.get("title")) + _words(paper.get("abstract"))):
            if word in DOMAIN_SINGLE or len(word) < 3:
                continue
            yearly[year][word] += 1

    early = Counter()
    late = Counter()
    early_total = 0
    late_total = 0
    for year, counter in yearly.items():
        if early_start <= year <= early_end:
            early.update(counter)
            early_total += yearly_papers[year]
        elif late_start <= year <= late_end:
            late.update(counter)
            late_total += yearly_papers[year]

    rows = []
    for word in set(early) | set(late):
        early_count = early[word]
        late_count = late[word]
        if early_count + late_count < 2:
            continue
        early_rate = early_count / early_total if early_total else 0.0
        late_rate = late_count / late_total if late_total else 0.0
        growth = (late_rate - early_rate) / early_rate if early_rate > 0 else None
        rows.append(
            {
                "term": word,
                "early_count": early_count,
                "late_count": late_count,
                "growth": round(growth, 3) if growth is not None else None,
                "new": early_count == 0,
                "small_base": early_count < 5,
            }
        )
    rows.sort(key=lambda item: (item["growth"] is None, -(item["growth"] or 0)))
    return {
        "early_range": f"{early_start}-{early_end}",
        "late_range": f"{late_start}-{late_end}",
        "incomplete_year": "2026",
        "keywords": rows[:limit],
        "note": "growth uses paper-count-normalized term rates; 2026 is incomplete and excluded from comparison",
    }


def get_analytics_summary(db_path, screened_path, statuses=None):
    papers = _load_papers(db_path)
    screened = _load_screened(screened_path)
    statuses = statuses or ["included"]
    analysis_papers = _filter_papers(papers, screened, statuses)
    home = get_home_stats(db_path, screened_path, topic_limit=10)
    return {
        "papers": home["papers"],
        "authors": home["authors"],
        "years": f"{home['year_min']}-{home['year_max']}",
        "doc_types": home["doc_types"],
        "topics": _extract_topics(analysis_papers, 10),
        "trend": publication_trend(analysis_papers),
        "top_authors": top_authors(analysis_papers),
        "emerging_keywords": emerging_keywords(analysis_papers),
        "scope": sorted(statuses),
        "note": home["note"],
    }


def map_data(db_path, corpus_path, screened_path, seed_id, limit=8):
    recommendation = recommendation_service.related_papers(
        db_path, corpus_path, screened_path, seed_id, limit=limit
    )
    if recommendation is None:
        return {"nodes": [], "links": [], "insufficient": True}

    seed = recommendation["seed_paper"]
    nodes = [
        {
            "id": seed["paper_id"],
            "name": (seed.get("title") or "untitled")[:70],
            "type": "paper",
            "is_seed": True,
        }
    ]
    links = []
    related = recommendation["related_papers"]
    for paper in related:
        nodes.append(
            {
                "id": paper["paper_id"],
                "name": (paper.get("title") or "untitled")[:70],
                "type": "paper",
                "is_seed": False,
            }
        )
        if paper.get("combined_score", 0) > 0:
            links.append(
                {
                    "source": seed["paper_id"],
                    "target": paper["paper_id"],
                    "relation": "similarity",
                    "weight": paper.get("combined_score"),
                }
            )

    terms = Counter(
        word
        for word in _words(seed.get("title")) + _words(seed.get("abstract"))
        if word not in STOPWORDS and word not in DOMAIN_SINGLE and len(word) >= 3
    )
    for term, _ in terms.most_common(6):
        topic_id = f"topic:{term}"
        nodes.append({"id": topic_id, "name": term, "type": "topic"})
        links.append({"source": seed["paper_id"], "target": topic_id, "relation": "paper_topic"})
        for paper in related:
            text_tokens = set(_words(paper.get("title"))) | set(_words(paper.get("abstract")))
            if term in text_tokens:
                links.append({"source": paper["paper_id"], "target": topic_id, "relation": "paper_topic"})

    return {
        "nodes": nodes,
        "links": links,
        "insufficient": False,
        "seed": seed["paper_id"],
        "note": "paper-paper edges are text similarity, not citation relations",
    }
