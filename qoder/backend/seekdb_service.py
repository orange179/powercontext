"""
seekdb integration layer for ResearchFlow.

seekdb is the primary data store. All CRUD and search operations go through seekdb.
An in-memory cache (_paper_cache) is populated from seekdb on startup for fast access.

Supports three connection modes:
1. Embedded: pyseekdb with local .db file (requires pylibseekdb)
2. Remote: pyseekdb connecting to seekdb server via host/port
3. Simulated: in-memory only fallback when seekdb is unavailable
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
_initialized = False

_paper_cache: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def _patch_torch_dll():
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


def _load_cache_from_seekdb():
    """Load all papers from seekdb into the in-memory cache on startup."""
    global _paper_cache
    if not _seekdb_available or _collection is None:
        return
    try:
        count = _collection.count()
        if count == 0:
            return
        result = _collection.get(limit=count)
        ids = result.get("ids", [])
        metadatas = result.get("metadatas", [])
        documents = result.get("documents", [])
        for i, pid in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            doc = documents[i] if i < len(documents) else ""
            paper = _reconstruct_paper(pid, meta, doc)
            _paper_cache[pid] = paper
        print(f"[seekdb] Loaded {len(_paper_cache)} papers from seekdb into cache")
    except Exception as e:
        print(f"[seekdb] Cache load error: {e}")


def _reconstruct_paper(pid: str, meta: dict, doc_text: str) -> dict:
    """Reconstruct a full paper dict from seekdb metadata and document text."""
    paper_json = meta.get("paper_json")
    if paper_json:
        try:
            return json.loads(paper_json)
        except (json.JSONDecode, TypeError):
            pass

    return {
        "id": pid,
        "title": meta.get("title", ""),
        "abstract": meta.get("abstract", ""),
        "content": meta.get("content", doc_text),
        "authors": json.loads(meta.get("authors", "[]")),
        "year": int(meta.get("year", 2024)),
        "tags": json.loads(meta.get("tags", "[]")),
        "source": meta.get("source", ""),
        "reading_status": meta.get("reading_status", "unread"),
        "created_at": meta.get("created_at", _now_iso()),
    }


def init_db():
    global _seekdb_mode_actual, _initialized
    if _initialized:
        return _seekdb_available
    
    if SEEKDB_MODE == "simulated":
        _seekdb_mode_actual = "simulated"
        _initialized = True
        print("[seekdb] Simulated mode (forced by config)")
        return False
    if SEEKDB_MODE == "embedded":
        ok = _try_init_embedded()
        if ok:
            _load_cache_from_seekdb()
        _initialized = True
        return ok
    if SEEKDB_MODE == "remote":
        ok = _try_init_remote()
        if ok:
            _load_cache_from_seekdb()
        _initialized = True
        return ok

    if _try_init_embedded():
        _load_cache_from_seekdb()
        _initialized = True
        return True
    if sys.platform == "win32" and _try_init_remote():
        _load_cache_from_seekdb()
        _initialized = True
        return True

    _seekdb_mode_actual = "simulated"
    _initialized = True
    print("[seekdb] Falling back to simulated mode")
    return False


def get_seekdb_mode():
    return _seekdb_mode_actual


def is_seekdb_available():
    return _seekdb_available


# ---------------------------------------------------------------------------
# Simulated helpers (fallback only)
# ---------------------------------------------------------------------------

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
# seekdb write helper
# ---------------------------------------------------------------------------

def _write_to_seekdb(paper: dict):
    """Write a paper to seekdb. Stores full paper JSON in metadata for reliable readback."""
    if not _seekdb_available or _collection is None:
        return
    doc_text = f"{paper['title']} {paper['abstract']} {paper['content']}"
    try:
        _collection.upsert(
            ids=[paper["id"]],
            documents=[doc_text],
            metadatas=[{
                "paper_json": json.dumps(paper, ensure_ascii=False),
                "title": paper["title"],
                "authors": json.dumps(paper["authors"], ensure_ascii=False),
                "year": str(paper["year"]),
                "tags": json.dumps(paper["tags"], ensure_ascii=False),
                "reading_status": paper.get("reading_status", "unread"),
            }],
        )
    except Exception as e:
        print(f"[seekdb] Write error for {paper['id']}: {e}")


# ---------------------------------------------------------------------------
# Public API — all operations go through seekdb as primary store
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

    _write_to_seekdb(paper)
    _paper_cache[paper["id"]] = paper.copy()
    return paper.copy()


def update_paper(paper_id: str, **fields) -> dict | None:
    paper = _paper_cache.get(paper_id)
    if paper is None:
        if _seekdb_available:
            try:
                result = _collection.get(ids=[paper_id])
                if result and result.get("ids"):
                    meta = result["metadatas"][0] if result.get("metadatas") else {}
                    doc = result["documents"][0] if result.get("documents") else ""
                    paper = _reconstruct_paper(paper_id, meta, doc)
                    _paper_cache[paper_id] = paper
            except Exception:
                pass
        if paper is None:
            return None

    paper.update(fields)
    _write_to_seekdb(paper)
    _paper_cache[paper_id] = paper.copy()
    return paper.copy()


def delete_paper(paper_id: str) -> bool:
    if paper_id in _paper_cache:
        del _paper_cache[paper_id]
    if _seekdb_available and _collection is not None:
        try:
            _collection.delete(ids=[paper_id])
        except Exception:
            pass
        return True
    return paper_id not in _paper_cache


def get_paper(paper_id: str) -> dict | None:
    paper = _paper_cache.get(paper_id)
    if paper is not None:
        return paper.copy()

    if _seekdb_available and _collection is not None:
        try:
            result = _collection.get(ids=[paper_id])
            if result and result.get("ids"):
                meta = result["metadatas"][0] if result.get("metadatas") else {}
                doc = result["documents"][0] if result.get("documents") else ""
                paper = _reconstruct_paper(paper_id, meta, doc)
                _paper_cache[paper_id] = paper
                return paper.copy()
        except Exception:
            pass
    return None


def list_papers(filters: dict | None = None) -> list[dict]:
    if _seekdb_available and _collection is not None:
        _load_cache_from_seekdb()

    results = list(_paper_cache.values())
    results = _apply_filters(results, filters)
    return [p.copy() for p in results]


def search(query: str, n_results: int = 10,
           filters: dict | None = None,
           search_mode: str = "hybrid") -> list[dict]:
    if _seekdb_available and _collection is not None:
        return _search_seekdb(query, n_results, filters, search_mode)
    return _search_simulated(query, n_results, filters, search_mode)


def _search_seekdb(query: str, n_results: int, filters: dict | None, search_mode: str) -> list[dict]:
    """Use seekdb's native vector query. Reconstructs paper data from seekdb metadata."""
    try:
        fetch_count = min(n_results * 3, 100)
        results_data = _collection.query(query_texts=query, n_results=fetch_count)

        if not results_data or not results_data.get('ids', [[]])[0]:
            return []

        ids = results_data['ids'][0]
        distances = results_data['distances'][0]
        metadatas = results_data.get('metadatas', [[]])[0]
        documents = results_data.get('documents', [[]])[0]

        results = []
        max_dist = max(distances) if distances else 1.0

        for i, pid in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            doc = documents[i] if i < len(documents) else ""
            paper = _reconstruct_paper(pid, meta, doc)

            if filters:
                if filters.get("year_min") and paper["year"] < int(filters["year_min"]):
                    continue
                if filters.get("year_max") and paper["year"] > int(filters["year_max"]):
                    continue
                if filters.get("tag") and filters["tag"] not in paper.get("tags", []):
                    continue
                if filters.get("reading_status") and paper.get("reading_status") != filters["reading_status"]:
                    continue
                if filters.get("author"):
                    aq = filters["author"].lower()
                    if not any(aq in a.lower() for a in paper.get("authors", [])):
                        continue

            dist = distances[i] if i < len(distances) else 0.0
            score = 1.0 - (dist / (max_dist + 0.001)) if max_dist > 0 else 1.0

            paper["score"] = round(score, 4)
            paper["search_mode"] = search_mode
            paper["distance"] = round(dist, 4)
            results.append(paper)

            if len(results) >= n_results:
                break

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    except Exception as e:
        print(f"[seekdb] Query error: {e}")
        _load_cache_from_seekdb()
        return _search_simulated(query, n_results, filters, search_mode)


def _search_simulated(query: str, n_results: int, filters: dict | None, search_mode: str) -> list[dict]:
    """Simulated search using in-memory pseudo-embeddings."""
    candidates = list(_paper_cache.values())
    candidates = _apply_filters(candidates, filters)

    if not candidates:
        return []

    query_tokens = _tokenize(query)
    scored = []

    for paper in candidates:
        doc_text = f"{paper['title']} {paper['abstract']} {paper['content']}"
        vec_score = 0.0
        kw_score = 0.0

        if search_mode in ("vector", "hybrid"):
            q_emb = _simple_embed(query)
            d_emb = _simple_embed(doc_text)
            vec_score = _cosine_sim(q_emb, d_emb)

        if search_mode in ("keyword", "hybrid"):
            doc_tokens = _tokenize(doc_text)
            kw_score = _bm25_score(query_tokens, doc_tokens)
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
        r = paper.copy()
        r["score"] = round(score, 4)
        r["search_mode"] = search_mode
        results.append(r)
    return results


def get_stats() -> dict:
    if _seekdb_available:
        _load_cache_from_seekdb()

    papers = list(_paper_cache.values())
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


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
