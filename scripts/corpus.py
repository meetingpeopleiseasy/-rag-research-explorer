#!/usr/bin/env python3
"""Shared helpers for corpus merging, dedup and conflict detection."""

import re
import unicodedata
from collections import Counter, defaultdict


def normalize_doi_value(doi):
    """Normalize a DOI to a bare, lowercase form (None when missing)."""
    if not isinstance(doi, str):
        return None
    value = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    value = value.strip()
    return value or None


def normalize_title(title):
    """Normalize a title for duplicate-candidate detection."""
    if not isinstance(title, str):
        return None
    value = unicodedata.normalize("NFKC", title).lower()
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def merge_unique(*lists):
    """Union several lists, preserving first-seen order."""
    seen = []
    for items in lists:
        for item in items or []:
            if item not in seen:
                seen.append(item)
    return seen


def _norm_venue(venue):
    return normalize_title(venue)


def _field_diffs(a, b):
    diffs = []
    ay, by = a.get("year"), b.get("year")
    if ay is not None and by is not None and ay != by:
        diffs.append("year")

    aa, ba = set(a.get("authors") or []), set(b.get("authors") or [])
    if aa and ba and aa != ba:
        diffs.append("authors")

    av, bv = _norm_venue(a.get("venue")), _norm_venue(b.get("venue"))
    if av and bv and av != bv:
        diffs.append("venue")
    return diffs


def fields_conflict(a, b):
    """True when title-matched records disagree on year/authors/venue."""
    return bool(_field_diffs(a, b))


def _canonicalize(raw):
    record = dict(raw)
    doi = normalize_doi_value(
        record.get("doi") or (record.get("externalIds") or {}).get("DOI")
    )
    record["doi_norm"] = doi
    record["normalized_title"] = normalize_title(record.get("title"))
    record["matched_queries"] = list(record.get("matched_queries") or [])
    record["matched_years"] = list(record.get("matched_years") or [])
    record["run_ids"] = list(record.get("run_ids") or [])
    if record.get("run_id"):
        record["run_ids"] = merge_unique(record["run_ids"], [record["run_id"]])

    record["openalex_ids"] = list(record.get("openalex_ids") or [])
    paper_id = record.get("paperId")
    if paper_id:
        record["openalex_ids"] = merge_unique(record["openalex_ids"], [paper_id])

    record.setdefault("relevance_status", "pending")
    record.setdefault("dedup_status", "unique")
    record.setdefault("conflicts", [])
    return record


def _register(doi_index, id_index, title_index, record, index):
    if record.get("doi_norm"):
        doi_index.setdefault(record["doi_norm"], index)
    if record.get("paperId"):
        id_index.setdefault(record["paperId"], index)
    if record.get("normalized_title") and not record.get("doi_norm"):
        title_index.setdefault(record["normalized_title"], index)


def _merge_into(existing, incoming, kind):
    merged = dict(existing)
    for field in (
        "title", "abstract", "year", "publicationDate", "venue", "type",
        "language", "citedByCount", "biblio", "doi",
    ):
        if not merged.get(field) and incoming.get(field):
            merged[field] = incoming[field]
    if not merged.get("authors"):
        merged["authors"] = incoming.get("authors")

    merged["matched_queries"] = merge_unique(
        merged.get("matched_queries"), incoming.get("matched_queries")
    )
    merged["matched_years"] = merge_unique(
        merged.get("matched_years"), incoming.get("matched_years")
    )
    merged["run_ids"] = merge_unique(merged.get("run_ids"), incoming.get("run_ids"))
    merged["openalex_ids"] = merge_unique(
        merged.get("openalex_ids"), incoming.get("openalex_ids")
    )
    merged["dedup_status"] = f"merged_by_{kind}"

    if (
        kind == "doi"
        and merged.get("normalized_title")
        and incoming.get("normalized_title")
        and merged["normalized_title"] != incoming["normalized_title"]
    ):
        merged.setdefault("review_notes", []).append("doi_match_with_different_titles")
    return merged


def _flag_title_duplicate_groups(papers):
    """Mark same-title records that were kept (not merged) for review."""
    groups = defaultdict(list)
    for index, paper in enumerate(papers):
        title = paper.get("normalized_title")
        if title:
            groups[title].append(index)

    records = []
    for title, indices in groups.items():
        if len(indices) < 2:
            continue
        members = [papers[index] for index in indices]
        dois = {member.get("doi_norm") for member in members}
        dois = {doi for doi in dois if doi}
        if not dois:
            # No-DOI same-title pairs were already merged or listed in conflicts.
            continue
        if len(dois) == len(members):
            reason = "same_title_different_doi"
        else:
            reason = "same_title_partial_doi"

        group_id = f"title-dup-{len(records) + 1}"
        for index in indices:
            paper = papers[index]
            paper.setdefault("review_notes", []).append(reason)
            paper.setdefault("title_duplicate_groups", []).append(group_id)
        records.append(
            {
                "group_id": group_id,
                "reason": reason,
                "paper_ids": [papers[index].get("paperId") for index in indices],
                "count": len(indices),
            }
        )
    return records


def merge_records(records):
    """Merge a pool of normalized records into deduplicated candidates.

    Precedence: DOI first, then OpenAlex ID, then normalized title for
    records without a DOI. Title-matched records that conflict on year,
    authors or venue are kept separately and recorded in `conflicts`.
    Same-title records with different (or partially missing) DOIs are kept
    and reported in `title_duplicate_groups` for manual review.
    """
    papers = []
    conflicts = []
    doi_index = {}
    id_index = {}
    title_index = {}
    doi_merge_keys = set()
    title_merge_keys = set()

    for raw in records:
        record = _canonicalize(raw)
        doi = record.get("doi_norm")
        paper_id = record.get("paperId")
        ntitle = record.get("normalized_title")

        target = None
        kind = None
        if doi and doi in doi_index:
            target, kind = doi_index[doi], "doi"
        elif paper_id and paper_id in id_index:
            target, kind = id_index[paper_id], "id"
        elif ntitle and not doi and ntitle in title_index:
            target, kind = title_index[ntitle], "title"

        if target is None:
            index = len(papers)
            papers.append(record)
            _register(doi_index, id_index, title_index, record, index)
            continue

        existing = papers[target]
        if kind == "title" and fields_conflict(existing, record):
            group_id = f"conflict-{len(conflicts) + 1}"
            conflicts.append(
                {
                    "group_id": group_id,
                    "reason": "same_title_conflicting_fields",
                    "paper_ids": [existing.get("paperId"), record.get("paperId")],
                    "fields": _field_diffs(existing, record),
                }
            )
            existing.setdefault("conflicts", []).append(group_id)
            record.setdefault("conflicts", []).append(group_id)
            index = len(papers)
            papers.append(record)
            _register(doi_index, id_index, title_index, record, index)
            continue

        if kind == "doi":
            doi_merge_keys.add(doi)
        elif kind == "title":
            title_merge_keys.add(ntitle)
        papers[target] = _merge_into(existing, record, kind)

    title_duplicate_groups = _flag_title_duplicate_groups(papers)
    return {
        "papers": papers,
        "conflicts": conflicts,
        "doi_duplicate_groups": len(doi_merge_keys),
        "title_duplicate_groups_merged": len(title_merge_keys),
        "title_duplicate_groups": title_duplicate_groups,
    }


AUTHOR_SIM_THRESHOLD = 0.5
ABSTRACT_SIM_THRESHOLD = 0.5
SHORT_TITLE_MAX_TOKENS = 1


def _tokens(text):
    if not isinstance(text, str):
        return set()
    return set(re.findall(r"[0-9a-z\u4e00-\u9fff]+", text.lower()))


def _jaccard(left, right):
    if not left or not right:
        return None
    intersection = len(left & right)
    union = len(left | right)
    return intersection / union if union else None


def _author_tokens(paper):
    tokens = set()
    for name in paper.get("authors") or []:
        if isinstance(name, str):
            normalized = name.lower().replace(",", " ")
            tokens |= set(re.findall(r"[a-z0-9]+", normalized))
    return tokens


def _abstract_tokens(paper):
    return _tokens(paper.get("abstract"))


def _venue_is_formal(venue):
    value = (venue or "").lower()
    if not value:
        return False
    return not any(key in value for key in ("arxiv", "ssrn", "zenodo"))


def _pick_representative(members):
    def score(member):
        total = 0
        if _venue_is_formal(member.get("venue")):
            total += 2
        if member.get("doi"):
            total += 1
        if isinstance(member.get("abstract"), str) and member.get("abstract").strip():
            total += 1
        return total

    return max(members, key=score).get("paperId")


def _title_token_count(title):
    if not isinstance(title, str):
        return 0
    return len(re.findall(r"[0-9a-z\u4e00-\u9fff]+", title))


def build_version_groups(papers):
    """Group different OpenAlex records that are versions of the same work.

    Only exact normalized titles are compared; title equality alone is never
    sufficient. Author and abstract token overlap are used as evidence:
      - confirmed_same_work: title equal and author/abstract overlap strong.
      - suspected_same_work: title equal but evidence missing or weak.
      - clearly different works: not grouped at all.
    """
    title_groups = defaultdict(list)
    for paper in papers:
        title = paper.get("normalized_title") or normalize_title(paper.get("title"))
        if title:
            title_groups[title].append(paper)

    groups = []
    for title, members in title_groups.items():
        if len(members) < 2:
            continue

        short_title = _title_token_count(title) <= SHORT_TITLE_MAX_TOKENS

        author_sims = []
        abstract_sims = []
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                author_sims.append(
                    _jaccard(_author_tokens(members[i]), _author_tokens(members[j]))
                )
                abstract_sims.append(
                    _jaccard(_abstract_tokens(members[i]), _abstract_tokens(members[j]))
                )

        author_sim = max((s for s in author_sims if s is not None), default=None)
        abstract_sim = max((s for s in abstract_sims if s is not None), default=None)

        if short_title:
            dois = {member.get("doi_norm") for member in members}
            dois = {doi for doi in dois if doi}
            same_doi = len(members) > 1 and len(dois) == 1
            strong_evidence = same_doi or (
                author_sim is not None
                and author_sim >= AUTHOR_SIM_THRESHOLD
                and abstract_sim is not None
                and abstract_sim >= ABSTRACT_SIM_THRESHOLD
            )
            if not strong_evidence:
                # Overly broad single-word titles collide across unrelated works.
                continue
            classification = "confirmed_same_work"
        elif author_sim is None and abstract_sim is None:
            classification = "suspected_same_work"
        elif (
            (author_sim is not None and author_sim >= AUTHOR_SIM_THRESHOLD)
            or (abstract_sim is not None and abstract_sim >= ABSTRACT_SIM_THRESHOLD)
        ):
            classification = "confirmed_same_work"
        elif (
            author_sim is not None
            and author_sim == 0.0
            and (abstract_sim is None or abstract_sim < ABSTRACT_SIM_THRESHOLD)
        ):
            # Same title, but authors and abstracts are clearly different works.
            continue
        else:
            classification = "suspected_same_work"

        groups.append(
            {
                "group_id": f"version-{len(groups) + 1}",
                "classification": classification,
                "normalized_title": title,
                "paper_ids": [member.get("paperId") for member in members],
                "representative_id": _pick_representative(members),
                "evidence": {
                    "author_sim": author_sim,
                    "abstract_sim": abstract_sim,
                },
            }
        )

    return groups


VALID_REVIEW_DECISIONS = {"same_work", "different_work", "uncertain"}


def apply_version_review(version_groups, review_decisions):
    """Overlay manual review decisions onto auto-generated version groups.

    `same_work` promotes a group to confirmed; `different_work` dissolves the
    group; `uncertain` keeps it as suspected. `pending` and unknown decisions
    leave the auto decision untouched. The function never mutates papers.
    """
    decisions = {
        group_id: decision
        for group_id, decision in (review_decisions or {}).items()
        if decision in VALID_REVIEW_DECISIONS
    }

    final_groups = []
    different_work_groups = []
    for group in version_groups:
        group_id = group.get("group_id")
        decision = decisions.get(group_id)
        if decision == "different_work":
            different_work_groups.append(
                {
                    "group_id": group_id,
                    "paper_ids": list(group.get("paper_ids") or []),
                }
            )
            continue

        updated = dict(group)
        if decision == "same_work":
            updated["classification"] = "confirmed_same_work"
            updated["review_decision"] = "same_work"
            updated["review_applied"] = True
        elif decision == "uncertain":
            updated["classification"] = "suspected_same_work"
            updated["review_decision"] = "uncertain"
            updated["review_applied"] = True
        final_groups.append(updated)

    return {
        "version_groups": final_groups,
        "different_work_groups": different_work_groups,
    }


def count_duplicates(records):
    """Count duplicate candidates by OpenAlex ID, DOI and normalized title."""
    id_counts = Counter()
    doi_counts = Counter()
    title_counts = Counter()

    for raw in records:
        record = _canonicalize(raw)
        if record.get("paperId"):
            id_counts[record["paperId"]] += 1
        if record.get("doi_norm"):
            doi_counts[record["doi_norm"]] += 1
        if record.get("normalized_title"):
            title_counts[record["normalized_title"]] += 1

    return {
        "total": len(records),
        "duplicate_by_id": sum(c - 1 for c in id_counts.values() if c > 1),
        "duplicate_by_doi": sum(c - 1 for c in doi_counts.values() if c > 1),
        "duplicate_by_title": sum(c - 1 for c in title_counts.values() if c > 1),
    }
