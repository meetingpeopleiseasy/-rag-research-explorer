from flask import Blueprint, current_app, jsonify, request

from services import ai_service, analytics_service, collection_service, paper_service, recommendation_service, search_service

api_bp = Blueprint("api", __name__)


def _positive_int(value, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _list_param(request, name):
    values = []
    for raw in request.args.getlist(name):
        values.extend(item.strip() for item in raw.split(",") if item.strip())
    return values


@api_bp.get("/search")
def api_search():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400
    page = _positive_int(request.args.get("page"), 1)
    per_page = _positive_int(request.args.get("per_page"), 10)
    years = _list_param(request, "years")
    if not years and request.args.get("year"):
        years = [request.args.get("year")]
    doc_types = _list_param(request, "doc_types")
    statuses = _list_param(request, "statuses")
    year_from = _positive_int(request.args.get("year_from"), None) if request.args.get("year_from") else None
    year_to = _positive_int(request.args.get("year_to"), None) if request.args.get("year_to") else None
    try:
        data = search_service.search_documents(
            current_app.config["DB_PATH"],
            current_app.config["CORPUS_PATH"],
            query,
            page=page,
            per_page=per_page,
            years=years,
            year_from=year_from,
            year_to=year_to,
            doc_types=doc_types,
            statuses=statuses,
            screened_path=current_app.config["SCREENED_PATH"],
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    default_id, _ = collection_service.get_or_create_default(
        current_app.config["COLLECTIONS_PATH"]
    )
    saved_ids = set(
        collection_service.collection_paper_ids(
            current_app.config["COLLECTIONS_PATH"], default_id
        )
    )
    for item in data["results"]:
        item["saved"] = item.get("paper_id") in saved_ids
    return jsonify(data)


@api_bp.get("/paper/<path:paper_id>")
def api_paper(paper_id):
    paper = paper_service.get_paper(current_app.config["DB_PATH"], paper_id)
    if paper is None:
        return jsonify({"error": "paper not found"}), 404
    versions = paper_service.get_versions(
        current_app.config["DB_PATH"],
        current_app.config["CORPUS_PATH"],
        paper_id,
    )
    return jsonify({"paper": paper, "versions": versions})


@api_bp.get("/paper/<path:paper_id>/related")
def api_related(paper_id):
    include_excluded = request.args.get("include_excluded") == "1"
    recommendation = recommendation_service.related_papers(
        current_app.config["DB_PATH"],
        current_app.config["CORPUS_PATH"],
        current_app.config["SCREENED_PATH"],
        paper_id,
        include_excluded=include_excluded,
    )
    if recommendation is None:
        return jsonify({"error": "paper not found"}), 404
    return jsonify(recommendation)


@api_bp.get("/collections")
def api_collections():
    return jsonify(
        {"collections": collection_service.list_collections(current_app.config["COLLECTIONS_PATH"])}
    )


@api_bp.get("/analytics/summary")
def api_analytics_summary():
    statuses = _list_param(request, "statuses") or ["included"]
    return jsonify(
        analytics_service.get_analytics_summary(
            current_app.config["DB_PATH"],
            current_app.config["SCREENED_PATH"],
            statuses=statuses,
        )
    )


@api_bp.get("/map/<path:paper_id>")
def api_map(paper_id):
    data = analytics_service.map_data(
        current_app.config["DB_PATH"],
        current_app.config["CORPUS_PATH"],
        current_app.config["SCREENED_PATH"],
        paper_id,
    )
    if data.get("insufficient"):
        return jsonify({"error": "paper not found", "insufficient": True}), 404
    return jsonify(data)


@api_bp.post("/collections")
def api_create_collection():
    payload = request.get_json(silent=True) or {}
    name = payload.get("name")
    description = payload.get("description", "")
    try:
        collection_id = collection_service.create_collection(
            current_app.config["COLLECTIONS_PATH"], name, description
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"id": collection_id, "name": name, "description": description}), 201


@api_bp.patch("/collections/<int:collection_id>")
def api_update_collection(collection_id):
    payload = request.get_json(silent=True) or {}
    try:
        result = collection_service.update_collection(
            current_app.config["COLLECTIONS_PATH"],
            collection_id,
            name=payload.get("name"),
            description=payload.get("description"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if result is None:
        return jsonify({"error": "collection not found"}), 404
    return jsonify({"id": collection_id})


@api_bp.delete("/collections/<int:collection_id>")
def api_delete_collection(collection_id):
    if not collection_service.delete_collection(
        current_app.config["COLLECTIONS_PATH"], collection_id
    ):
        return jsonify({"error": "collection not found"}), 404
    return jsonify({"deleted": collection_id})


@api_bp.get("/collections/default")
def api_default_collection():
    collection_id, name = collection_service.get_or_create_default(
        current_app.config["COLLECTIONS_PATH"]
    )
    return jsonify({"id": collection_id, "name": name})


@api_bp.post("/collections/quick-save")
def api_quick_save():
    payload = request.get_json(silent=True) or {}
    paper_id = payload.get("paper_id")
    collection_name = (payload.get("collection_name") or "").strip() or None
    if not paper_id:
        return jsonify({"error": "paper_id is required"}), 400
    if paper_service.get_paper(current_app.config["DB_PATH"], paper_id) is None:
        return jsonify({"error": "paper not found"}), 404
    try:
        result = collection_service.quick_save(
            current_app.config["COLLECTIONS_PATH"], paper_id, collection_name
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@api_bp.get("/collections/<int:collection_id>")
def api_get_collection(collection_id):
    collection = collection_service.get_collection(
        current_app.config["COLLECTIONS_PATH"],
        current_app.config["DB_PATH"],
        collection_id,
        screened_path=current_app.config["SCREENED_PATH"],
    )
    if collection is None:
        return jsonify({"error": "collection not found"}), 404
    return jsonify(collection)


@api_bp.get("/collections/<int:collection_id>/export")
def api_export_citations(collection_id):
    citations = collection_service.export_citations(
        current_app.config["COLLECTIONS_PATH"],
        current_app.config["DB_PATH"],
        collection_id,
    )
    return jsonify({"citations": citations})


@api_bp.post("/collections/<int:collection_id>/papers")
def api_add_paper(collection_id):
    payload = request.get_json(silent=True) or {}
    paper_id = payload.get("paper_id")
    if not paper_id:
        return jsonify({"error": "paper_id is required"}), 400
    if paper_service.get_paper(current_app.config["DB_PATH"], paper_id) is None:
        return jsonify({"error": "paper not found"}), 404
    if collection_service.add_paper(
        current_app.config["COLLECTIONS_PATH"], collection_id, paper_id
    ) is None:
        return jsonify({"error": "collection not found"}), 404
    return jsonify({"added": paper_id})


@api_bp.delete("/collections/<int:collection_id>/papers/<path:paper_id>")
def api_remove_paper(collection_id, paper_id):
    collection_service.remove_paper(
        current_app.config["COLLECTIONS_PATH"], collection_id, paper_id
    )
    return jsonify({"removed": paper_id})


@api_bp.patch("/collections/<int:collection_id>/papers/<path:paper_id>")
def api_set_reading_status(collection_id, paper_id):
    payload = request.get_json(silent=True) or {}
    reading_status = payload.get("reading_status")
    try:
        collection_service.set_reading_status(
            current_app.config["COLLECTIONS_PATH"], collection_id, paper_id, reading_status
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"paper_id": paper_id, "reading_status": reading_status})


@api_bp.post("/ai/paper-analysis")
def ai_paper_analysis():
    payload = request.get_json(silent=True) or {}
    paper_id = payload.get("paper_id")
    analysis_type = payload.get("analysis_type")
    if not paper_id or analysis_type not in ai_service.ALLOWED_ANALYSIS:
        return jsonify({"error": "paper_id and a valid analysis_type are required"}), 400

    paper = paper_service.get_paper(current_app.config["DB_PATH"], paper_id)
    if paper is None:
        return jsonify({"error": "paper not found"}), 404

    try:
        result = ai_service.analyze_paper(paper, analysis_type)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(
        {
            "paper_id": paper_id,
            "analysis_type": analysis_type,
            "basis": "Abstract / Metadata",
            "cached": result.get("cached", False),
            "content": result["content"],
        }
    )


def _fetch_selected_papers(paper_ids):
    papers = []
    for paper_id in paper_ids:
        paper = paper_service.get_paper(current_app.config["DB_PATH"], paper_id)
        if paper is None:
            return None, paper_id
        papers.append(paper)
    return papers, None


@api_bp.post("/ai/research-overview")
def ai_research_overview():
    payload = request.get_json(silent=True) or {}
    query = (payload.get("query") or "").strip()
    paper_ids = payload.get("paper_ids") or []
    if not query:
        return jsonify({"error": "query is required"}), 400
    if not isinstance(paper_ids, list) or not paper_ids:
        return jsonify({"error": "paper_ids must be a non-empty list"}), 400

    papers, missing = _fetch_selected_papers(paper_ids)
    if papers is None:
        return jsonify({"error": f"paper not found: {missing}"}), 404

    try:
        result = ai_service.build_overview(query, papers)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502
    context_id, context_info = ai_service.create_context(query, papers)
    return jsonify(
        {
            "query": query,
            "basis": "Abstract / Metadata",
            "content": result["content"],
            "structured": result.get("structured"),
            "citations": result["citations"],
            "context_id": context_id,
            "context": context_info,
        }
    )


@api_bp.post("/ai/qa")
def ai_qa():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    context_id = payload.get("context_id")
    paper_ids = payload.get("paper_ids") or []
    if not question:
        return jsonify({"error": "question is required"}), 400

    if context_id:
        result = ai_service.answer_followup(context_id, question)
        if result is None:
            return jsonify({"error": "context not found"}), 404
        context = ai_service.get_context(context_id)
    else:
        if not isinstance(paper_ids, list) or not paper_ids:
            return jsonify({"error": "paper_ids must be a non-empty list or context_id is required"}), 400
        papers, missing = _fetch_selected_papers(paper_ids)
        if papers is None:
            return jsonify({"error": f"paper not found: {missing}"}), 404
        try:
            result = ai_service.build_qa(question, papers)
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 502
        context = {"paper_count": len(papers), "paper_ids": paper_ids}
    return jsonify(
        {
            "question": question,
            "basis": "Abstract / Metadata",
            "content": result["content"],
            "citations": result["citations"],
            "context": context,
        }
    )


@api_bp.get("/ai/context/<context_id>")
def ai_get_context(context_id):
    context = ai_service.get_context(context_id)
    if context is None:
        return jsonify({"error": "context not found"}), 404
    return jsonify(context)


@api_bp.delete("/ai/context/<context_id>")
def ai_clear_context(context_id):
    if not ai_service.clear_context(context_id):
        return jsonify({"error": "context not found"}), 404
    return jsonify({"cleared": context_id})


@api_bp.post("/ai/compare")
def ai_compare():
    payload = request.get_json(silent=True) or {}
    paper_ids = payload.get("paper_ids") or []
    if not isinstance(paper_ids, list) or not (2 <= len(paper_ids) <= 5):
        return jsonify({"error": "paper_ids must contain 2 to 5 papers"}), 400

    papers, missing = _fetch_selected_papers(paper_ids)
    if papers is None:
        return jsonify({"error": f"paper not found: {missing}"}), 404

    try:
        result = ai_service.build_comparison(papers)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(
        {
            "basis": "Abstract / Metadata",
            "content": result["content"],
            "structured": result.get("structured"),
            "citations": result["citations"],
        }
    )
