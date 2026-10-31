DOC_TYPE_LABELS = {
    "conference_paper": "Conference paper",
    "journal_article": "Journal article",
    "preprint": "Preprint",
    "review": "Review",
    "software_or_dataset": "Software / dataset",
    "unknown": "Unknown",
}

STATUS_LABELS = {
    "included": "Included",
    "uncertain": "Uncertain",
    "excluded": "Excluded",
    "pending": "Pending",
}


def doc_type_label(value):
    return DOC_TYPE_LABELS.get(value, (value or "").replace("_", " ").title())


def status_label(value):
    return STATUS_LABELS.get(value, (value or "").capitalize())
