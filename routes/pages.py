from flask import Blueprint, abort, current_app, render_template, request

from services import ai_service, analytics_service, collection_service, paper_service, recommendation_service, search_service

pages_bp = Blueprint("pages", __name__)


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


@pages_bp.get("/")
def index():
    stats = analytics_service.get_home_stats(
        current_app.config["DB_PATH"],
        current_app.config["SCREENED_PATH"],
    )
    return render_template("index.html", stats=stats)


@pages_bp.get("/search")
def search_page():
    query = (request.args.get("q") or "").strip()
    page = _positive_int(request.args.get("page"), 1)
    years = _list_param(request, "years")
    if not years and request.args.get("year"):
        years = [request.args.get("year")]
    doc_types = _list_param(request, "doc_types")
    statuses = _list_param(request, "statuses")
    year_from = _positive_int(request.args.get("year_from"), None) if request.args.get("year_from") else None
    year_to = _positive_int(request.args.get("year_to"), None) if request.args.get("year_to") else None
    filter_options = search_service.get_filter_options(current_app.config["SCREENED_PATH"])

    if query:
        try:
            data = search_service.search_documents(
                current_app.config["DB_PATH"],
                current_app.config["CORPUS_PATH"],
                query,
                page=page,
                per_page=10,
                years=years,
                year_from=year_from,
                year_to=year_to,
                doc_types=doc_types,
                statuses=statuses,
                screened_path=current_app.config["SCREENED_PATH"],
            )
        except ValueError as exc:
            data = {
                "query": query,
                "total": 0,
                "page": 1,
                "per_page": 10,
                "results": [],
                "years": years,
                "year_from": year_from,
                "year_to": year_to,
                "doc_types": doc_types,
                "statuses": statuses,
                "error": str(exc),
            }
    else:
        data = {
            "query": "",
            "total": 0,
            "page": 1,
            "per_page": 10,
            "results": [],
            "years": years,
            "year_from": year_from,
            "year_to": year_to,
            "doc_types": doc_types,
            "statuses": statuses,
        }
    if query and data.get("results"):
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
    return render_template(
        "search.html",
        data=data,
        selected_years=years,
        selected_doc_types=doc_types,
        selected_statuses=statuses,
        filter_options=filter_options,
    )


@pages_bp.get("/paper/<path:paper_id>")
def paper_detail(paper_id):
    paper = paper_service.get_paper(current_app.config["DB_PATH"], paper_id)
    if paper is None:
        abort(404)
    versions = paper_service.get_versions(
        current_app.config["DB_PATH"],
        current_app.config["CORPUS_PATH"],
        paper_id,
    )
    return render_template(
        "paper.html",
        paper=paper,
        versions=versions,
        citation_apa=ai_service.format_citation(paper, "apa"),
        citation_ieee=ai_service.format_citation(paper, "ieee"),
        saved=collection_service.is_saved(current_app.config["COLLECTIONS_PATH"], paper_id),
    )


@pages_bp.get("/explore/<path:paper_id>")
def explore(paper_id):
    paper = paper_service.get_paper(current_app.config["DB_PATH"], paper_id)
    if paper is None:
        abort(404)
    recommendation = recommendation_service.related_papers(
        current_app.config["DB_PATH"],
        current_app.config["CORPUS_PATH"],
        current_app.config["SCREENED_PATH"],
        paper_id,
        include_excluded=request.args.get("include_excluded") == "1",
    )
    versions = paper_service.get_versions(
        current_app.config["DB_PATH"],
        current_app.config["CORPUS_PATH"],
        paper_id,
    )
    origin = request.args.get("from")
    return render_template(
        "explore.html",
        paper=paper,
        versions=versions,
        recommendation=recommendation,
        origin=origin,
    )


@pages_bp.get("/collections")
def collections_list():
    collections = collection_service.list_collections(current_app.config["COLLECTIONS_PATH"])
    return render_template("collections.html", collections=collections)


@pages_bp.get("/collections/<int:collection_id>")
def collection_detail(collection_id):
    collection = collection_service.get_collection(
        current_app.config["COLLECTIONS_PATH"],
        current_app.config["DB_PATH"],
        collection_id,
        screened_path=current_app.config["SCREENED_PATH"],
    )
    if collection is None:
        abort(404)
    return render_template("collection.html", collection=collection)


@pages_bp.get("/overview")
def research_overview():
    query = (request.args.get("q") or "").strip()
    collection_id = request.args.get("collection_id")
    source_papers = []
    source_label = ""

    if query:
        data = search_service.search_documents(
            current_app.config["DB_PATH"],
            current_app.config["CORPUS_PATH"],
            query,
            page=1,
            per_page=20,
                screened_path=current_app.config["SCREENED_PATH"],
        )
        source_papers = [
            {
                "paper_id": item["paper_id"],
                "title": item["title"],
                "authors": item["authors"],
                "year": item["year"],
            }
            for item in data["results"]
        ]
        source_label = f"query “{query}”"
    elif collection_id:
        collection = collection_service.get_collection(
            current_app.config["COLLECTIONS_PATH"],
            current_app.config["DB_PATH"],
            int(collection_id),
        )
        if collection is not None:
            source_papers = collection["papers"][:20]
            source_label = f"collection “{collection['name']}”"

    return render_template(
        "overview.html",
        source_papers=source_papers,
        source_label=source_label,
        query=query,
        collection_id=collection_id,
    )


@pages_bp.get("/analytics")
def analytics():
    statuses = _list_param(request, "statuses") or ["included"]
    include_uncertain = "uncertain" in statuses
    return render_template(
        "analytics.html",
        statuses=",".join(statuses),
        include_uncertain=include_uncertain,
    )


@pages_bp.get("/map/<path:paper_id>")
def research_map(paper_id):
    paper = paper_service.get_paper(current_app.config["DB_PATH"], paper_id)
    if paper is None:
        abort(404)
    return render_template("map.html", paper=paper)
