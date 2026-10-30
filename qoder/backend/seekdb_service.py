"""
seekdb integration layer for ResearchFlow.

Supports three modes:
1. Embedded mode: uses pyseekdb with local .db file (Linux only, requires pylibseekdb)
2. Remote server mode: connects to seekdb server via host/port (cross-platform)
3. Simulated mode: in-memory storage with basic text matching (demo/fallback)

The mode is auto-detected based on platform, pyseekdb availability, and config.
"""

import json
import math
import os
import re
import sys
import uuid
from collections import defaultdict

from config import (
    COLLECTION_NAME,
    DB_PATH,
    EMBEDDING_DIMENSION,
    SEEKDB_MODE,
)

SEEKDB_HOST = os.environ.get("SEEKDB_HOST", "localhost")
SEEKDB_PORT = int(os.environ.get("SEEKDB_PORT", "2881"))

_seekdb_available = False
_seekdb_mode_actual = "uninitialized"
_client = None
_collection = None


def _patch_torch_dll():
    """Workaround for torch DLL loading issue on Windows."""
    if sys.platform != "win32":
        return
    original = os.add_dll_directory

    def patched(path):
        try:
            return original(path)
        except OSError:
            class _Ctx:
                def __enter__(self): return self
                def __exit__(self, *a): pass
            return _Ctx()

    os.add_dll_directory = patched


def _try_init_embedded():
    global _seekdb_available, _seekdb_mode_actual, _client, _collection
    _patch_torch_dll()
    try:
        import pyseekdb
        _client = pyseekdb.Client(path=DB_PATH)
        _collection = _client.get_or_create_collection(name=COLLECTION_NAME)
        _seekdb_available = True
        _seekdb_mode_actual = "embedded"
        print(f"[seekdb] Embedded mode at {DB_PATH}")
        return True
    except Exception as e:
        print(f"[seekdb] Embedded mode unavailable: {e}")
        return False


def _try_init_remote():
    global _seekdb_available, _seekdb_mode_actual, _client, _collection
    _patch_torch_dll()
    try:
        import pyseekdb
        _client = pyseekdb.Client(host=SEEKDB_HOST, port=SEEKDB_PORT)
        _collection = _client.get_or_create_collection(name=COLLECTION_NAME)
        _seekdb_available = True
        _seekdb_mode_actual = "remote"
        print(f"[seekdb] Remote mode: {SEEKDB_HOST}:{SEEKDB_PORT}")
        return True
    except Exception as e:
        print(f"[seekdb] Remote mode unavailable: {e}")
        return False


def init_db():
    global _seekdb_mode_actual
    if SEEKDB_MODE == "simulated":
        _seekdb_mode_actual = "simulated"
        print("[seekdb] Simulated mode (forced by config)")
        return False
    if SEEKDB_MODE == "embedded":
        return _try_init_embedded()
    if SEEKDB_MODE == "remote":
        return _try_init_remote()
    # auto: try embedded first (works on Windows with pylibseekdb), then remote, then simulated
    if _try_init_embedded():
        return True
    if sys.platform != "win32":
        pass  # Already tried embedded above
    else:
        if _try_init_remote():
            return True
    _seekdb_mode_actual = "simulated"
    print("[seekdb] Falling back to simulated mode")
    return False


def get_seekdb_mode():
    return _seekdb_mode_actual


def is_seekdb_available():
    return _seekdb_available


# ---------------------------------------------------------------------------
# Simulated in-memory store (fallback / demo mode)
# ---------------------------------------------------------------------------

_sim_papers: dict[str, dict] = {}


def _simple_embed(text: str) -> list[float]:
    text = text.lower()
    vec = [0.0] * EMBEDDING_DIMENSION
    for i, ch in enumerate(text):
        idx = (ord(ch) * 31 + i) % EMBEDDING_DIMENSION
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine_sim(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r'[\w]+', text.lower()) if len(w) > 1]


def _bm25_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    tf_map = defaultdict(int)
    for t in doc_tokens:
        tf_map[t] += 1
    return sum(tf_map[qt] / (tf_map[qt] + 1.0) for qt in query_tokens if qt in tf_map)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_paper(paper_id: str, title: str, abstract: str, content: str,
              authors: list[str], year: int, tags: list[str],
              source: str = "", reading_status: str = "unread") -> dict:
    paper = {
        "id": paper_id or str(uuid.uuid4()),
        "title": title,
        "abstract": abstract,
        "content": content,
        "authors": authors,
        "year": year,
        "tags": tags,
        "source": source,
        "reading_status": reading_status,
        "created_at": _now_iso(),
    }

    if _seekdb_available and _collection is not None:
        doc_text = f"{title} {abstract} {content}"
        try:
            _collection.upsert(
                ids=[paper["id"]],
                documents=[doc_text],
                metadatas=[{
                    "title": title,
                    "authors": json.dumps(authors),
                    "year": str(year),
                    "tags": json.dumps(tags),
                    "reading_status": reading_status,
                }],
            )
        except Exception:
            pass
        # Also store in _sim_papers with embeddings for fallback
        paper["_embedding"] = _simple_embed(doc_text)
        paper["_tokens"] = _tokenize(doc_text)
        _sim_papers[paper["id"]] = paper
    else:
        doc_text = f"{title} {abstract} {content}"
        paper["_embedding"] = _simple_embed(doc_text)
        paper["_tokens"] = _tokenize(doc_text)
        _sim_papers[paper["id"]] = paper

    return _public_paper(paper)


def update_paper(paper_id: str, **fields) -> dict | None:
    if paper_id not in _sim_papers:
        return None
    paper = _sim_papers[paper_id]
    paper.update(fields)

    if _seekdb_available and _collection is not None:
        doc_text = f"{paper['title']} {paper['abstract']} {paper['content']}"
        try:
            _collection.upsert(
                ids=[paper_id],
                documents=[doc_text],
                metadatas=[{
                    "title": paper["title"],
                    "authors": json.dumps(paper["authors"]),
                    "year": str(paper["year"]),
                    "tags": json.dumps(paper["tags"]),
                    "reading_status": paper.get("reading_status", "unread"),
                }],
            )
        except Exception:
            pass

    return _public_paper(paper)


def delete_paper(paper_id: str) -> bool:
    if paper_id not in _sim_papers:
        return False
    del _sim_papers[paper_id]
    if _seekdb_available and _collection is not None:
        try:
            _collection.delete(ids=[paper_id])
        except Exception:
            pass
    return True


def get_paper(paper_id: str) -> dict | None:
    paper = _sim_papers.get(paper_id)
    return _public_paper(paper) if paper else None


def list_papers(filters: dict | None = None) -> list[dict]:
    results = list(_sim_papers.values())
    results = _apply_filters(results, filters)
    return [_public_paper(p) for p in results]


def search(query: str, n_results: int = 10,
           filters: dict | None = None,
           search_mode: str = "hybrid") -> list[dict]:
    # Use seekdb's native query when available
    if _seekdb_available and _collection is not None:
        return _search_seekdb(query, n_results, filters, search_mode)
    # Fallback to simulated search
    return _search_simulated(query, n_results, filters, search_mode)


def _search_seekdb(query: str, n_results: int, filters: dict | None, search_mode: str) -> list[dict]:
    """Use seekdb's native vector query for semantic search."""
    try:
        # seekdb query returns results with distances
        results_data = _collection.query(query_texts=query, n_results=n_results * 2)

        if not results_data or not results_data.get('ids', [[]])[0]:
            return []

        ids = results_data['ids'][0]
        distances = results_data['distances'][0]
        documents = results_data['documents'][0]

        # Convert distances to scores (lower distance = higher score)
        # Normalize scores to 0-1 range
        max_dist = max(distances) if distances else 1.0
        results = []

        for i, (pid, dist, doc) in enumerate(zip(ids, distances, documents)):
            paper = _sim_papers.get(pid)
            if not paper:
                continue

            # Apply filters
            if filters:
                if filters.get("year_min") and paper["year"] < int(filters["year_min"]):
                    continue
                if filters.get("year_max") and paper["year"] > int(filters["year_max"]):
                    continue
                if filters.get("tag") and filters["tag"] not in paper.get("tags", []):
                    continue
                if filters.get("reading_status") and paper.get("reading_status") != filters["reading_status"]:
                    continue

            # Convert distance to similarity score (inverse relationship)
            score = 1.0 - (dist / (max_dist + 0.001)) if max_dist > 0 else 1.0

            r = _public_paper(paper)
            r["score"] = round(score, 4)
            r["search_mode"] = search_mode
            r["distance"] = round(dist, 4)
            results.append(r)

        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:n_results]

    except Exception as e:
        print(f"[seekdb] Query error: {e}")
        return _search_simulated(query, n_results, filters, search_mode)


def _search_simulated(query: str, n_results: int, filters: dict | None, search_mode: str) -> list[dict]:
    """Simulated search using in-memory embeddings."""
    candidates = list(_sim_papers.values())
    candidates = _apply_filters(candidates, filters)

    if not candidates:
        return []

    query_tokens = _tokenize(query)
    scored = []

    for paper in candidates:
        vec_score = 0.0
        kw_score = 0.0

        if search_mode in ("vector", "hybrid"):
            q_emb = _simple_embed(query)
            vec_score = _cosine_sim(q_emb, paper["_embedding"])

        if search_mode in ("keyword", "hybrid"):
            kw_score = _bm25_score(query_tokens, paper["_tokens"])
            if any(t in paper["title"].lower() for t in query_tokens):
                kw_score *= 2.0

        if search_mode == "hybrid":
            final = 0.6 * vec_score + 0.4 * kw_score
        elif search_mode == "vector":
            final = vec_score
        else:
            final = kw_score

        scored.append((final, paper))

    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, paper in scored[:n_results]:
        r = _public_paper(paper)
        r["score"] = round(score, 4)
        r["search_mode"] = search_mode
        results.append(r)
    return results


def get_stats() -> dict:
    papers = list(_sim_papers.values())
    tag_counts = defaultdict(int)
    status_counts = defaultdict(int)
    year_counts = defaultdict(int)
    for p in papers:
        for t in p.get("tags", []):
            tag_counts[t] += 1
        status_counts[p.get("reading_status", "unread")] += 1
        year_counts[p["year"]] += 1

    return {
        "total_papers": len(papers),
        "seekdb_mode": get_seekdb_mode(),
        "tags": dict(tag_counts),
        "reading_status": dict(status_counts),
        "papers_by_year": dict(sorted(year_counts.items())),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_filters(items: list[dict], filters: dict | None) -> list[dict]:
    if not filters:
        return items
    if filters.get("year_min"):
        items = [p for p in items if p["year"] >= int(filters["year_min"])]
    if filters.get("year_max"):
        items = [p for p in items if p["year"] <= int(filters["year_max"])]
    if filters.get("tag"):
        items = [p for p in items if filters["tag"] in p.get("tags", [])]
    if filters.get("reading_status"):
        items = [p for p in items if p.get("reading_status") == filters["reading_status"]]
    if filters.get("author"):
        q = filters["author"].lower()
        items = [p for p in items if any(q in a.lower() for a in p.get("authors", []))]
    return items


def _public_paper(paper: dict) -> dict:
    return {k: v for k, v in paper.items() if not k.startswith("_")}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
