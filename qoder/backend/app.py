"""
ResearchFlow - Flask Backend
科研文献智能检索助手

REST API endpoints:
  POST   /api/papers          - Add a paper
  GET    /api/papers          - List papers (with optional filters)
  GET    /api/papers/<id>     - Get a paper
  PUT    /api/papers/<id>     - Update a paper
  DELETE /api/papers/<id>     - Delete a paper
  POST   /api/search          - Hybrid search
  GET    /api/stats            - Library statistics
  POST   /api/import-sample   - Import sample papers
  GET    /api/health           - Health check with seekdb status
"""

import json
import os
import sys
import uuid

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(__file__))

import seekdb_service
from config import FLASK_DEBUG, FLASK_HOST, FLASK_PORT

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)


@app.before_request
def _ensure_db():
    if not _db_initialized:
        seekdb_service.init_db()


_db_initialized = False


def _init():
    global _db_initialized
    if not _db_initialized:
        seekdb_service.init_db()
        _db_initialized = True


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------------------------------------------------------------------
# Health & Stats
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "seekdb_available": seekdb_service.is_seekdb_available(),
        "seekdb_mode": seekdb_service.get_seekdb_mode(),
    })


@app.route("/api/stats")
def stats():
    _init()
    return jsonify(seekdb_service.get_stats())


# ---------------------------------------------------------------------------
# Papers CRUD
# ---------------------------------------------------------------------------

@app.route("/api/papers", methods=["POST"])
def add_paper():
    _init()
    data = request.get_json(force=True)
    paper_id = data.get("id") or str(uuid.uuid4())
    paper = seekdb_service.add_paper(
        paper_id=paper_id,
        title=data.get("title", ""),
        abstract=data.get("abstract", ""),
        content=data.get("content", ""),
        authors=data.get("authors", []),
        year=int(data.get("year", 2024)),
        tags=data.get("tags", []),
        source=data.get("source", ""),
        reading_status=data.get("reading_status", "unread"),
    )
    return jsonify(paper), 201


@app.route("/api/papers", methods=["GET"])
def list_papers():
    _init()
    filters = {}
    for key in ("year_min", "year_max", "tag", "reading_status", "author"):
        val = request.args.get(key)
        if val:
            filters[key] = val
    papers = seekdb_service.list_papers(filters or None)
    return jsonify({"papers": papers, "total": len(papers)})


@app.route("/api/papers/<paper_id>", methods=["GET"])
def get_paper(paper_id):
    _init()
    paper = seekdb_service.get_paper(paper_id)
    if paper is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(paper)


@app.route("/api/papers/<paper_id>", methods=["PUT"])
def update_paper(paper_id):
    _init()
    data = request.get_json(force=True)
    allowed = {"title", "abstract", "content", "authors", "year", "tags",
               "source", "reading_status"}
    fields = {k: v for k, v in data.items() if k in allowed}
    paper = seekdb_service.update_paper(paper_id, **fields)
    if paper is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(paper)


@app.route("/api/papers/<paper_id>", methods=["DELETE"])
def delete_paper(paper_id):
    _init()
    ok = seekdb_service.delete_paper(paper_id)
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": True})


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@app.route("/api/search", methods=["POST"])
def search():
    _init()
    data = request.get_json(force=True)
    query = data.get("query", "")
    n_results = int(data.get("n_results", 10))
    search_mode = data.get("search_mode", "hybrid")
    filters = data.get("filters")

    if not query.strip():
        return jsonify({"error": "query is required"}), 400

    results = seekdb_service.search(
        query=query,
        n_results=n_results,
        filters=filters,
        search_mode=search_mode,
    )
    return jsonify({
        "query": query,
        "search_mode": search_mode,
        "results": results,
        "total": len(results),
    })


# ---------------------------------------------------------------------------
# Sample data import
# ---------------------------------------------------------------------------

@app.route("/api/import-sample", methods=["POST"])
def import_sample():
    _init()
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    sample_path = os.path.join(data_dir, "sample_papers.json")
    if not os.path.exists(sample_path):
        return jsonify({"error": "sample_papers.json not found"}), 404

    with open(sample_path, "r", encoding="utf-8") as f:
        papers = json.load(f)

    imported = []
    for p in papers:
        paper = seekdb_service.add_paper(
            paper_id=p.get("id", str(uuid.uuid4())),
            title=p["title"],
            abstract=p.get("abstract", ""),
            content=p.get("content", ""),
            authors=p.get("authors", []),
            year=int(p.get("year", 2024)),
            tags=p.get("tags", []),
            source=p.get("source", ""),
            reading_status=p.get("reading_status", "unread"),
        )
        imported.append(paper["id"])

    return jsonify({"imported": len(imported), "ids": imported})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mode = seekdb_service.get_seekdb_mode()
    print(f"\n  ResearchFlow - 科研文献智能检索助手")
    print(f"  seekdb mode: {mode} (will initialize on first data request)")
    print(f"  Running at http://localhost:{FLASK_PORT}\n")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
