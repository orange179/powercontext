"""Research Assistant Backend - 文献整理与知识检索助手

核心能力由 PowerContext 提供（进程内 ASGI + SQLite，无需外部服务）：
- 文献入库与检索：每篇文献作为一条 Memory 写入 PowerContext 的共享 Scope，
  检索直接调用 PowerContext 的 search_memory（FTS 全文检索）。
- 用户偏好记忆：偏好写入每个用户独立的 Scope，之后从 PowerContext 召回，
  用于生成个性化推荐（数据流：偏好 Memory -> 召回 -> 标签 -> 文献检索）。

PowerContext 不是"仅安装/测试连接"，而是承载了本项目的入库、检索、记忆全流程。
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pc_runtime import embedded_powercontext

from powercontext.client import PowerContextClient
from powercontext.http import (
    CreateScopeRequest,
    ListMemoryEntriesRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
)

DATA_DIR = Path(
    os.environ.get("RESEARCH_ASSISTANT_DATA_DIR")
    or Path(__file__).resolve().parent / ".powercontext-data"
)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

state: dict[str, Any] = {
    "pc": None,
    "library_scope": None,
    "user_scopes": {},
    "papers": [],
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with embedded_powercontext(DATA_DIR) as pc:
        state["pc"] = pc
        caps = await pc.get_capabilities()
        print(f"[startup] PowerContext ready, search_modes={caps.search_modes}")
        scope = await pc.create_scope(
            CreateScopeRequest(
                title="文献库",
                summary="Research Assistant 的共享文献检索库",
                idempotency_key="research-assistant:library",
            )
        )
        state["library_scope"] = scope.scope_id
        state["papers"] = await _load_library(pc, scope.scope_id)
        print(f"[startup] restored {len(state['papers'])} papers from PowerContext")
        yield
    state["pc"] = None


app = FastAPI(title="Research Assistant API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchQuery(BaseModel):
    query: str
    top_k: int = 10


class PreferencePayload(BaseModel):
    user_id: str | None = None
    preferred_tags: list[str] = []


def _pc() -> PowerContextClient:
    client = state["pc"]
    if client is None:
        raise HTTPException(status_code=503, detail="PowerContext 尚未就绪")
    return client


async def _user_scope(user_id: str) -> str:
    if user_id in state["user_scopes"]:
        return state["user_scopes"][user_id]
    scope = await _pc().create_scope(
        CreateScopeRequest(
            title=f"用户 {user_id} 的偏好",
            summary="保存该用户的文献检索偏好与阅读记忆",
            idempotency_key=f"research-assistant:user:{user_id}",
        )
    )
    state["user_scopes"][user_id] = scope.scope_id
    return scope.scope_id


DOC_LABELS = {
    "标题": "title",
    "作者": "authors",
    "摘要": "abstract",
    "关键词": "keywords",
    "标签": "tags",
    "备注": "notes",
    "时间": "created_at",
}


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _memory_text(doc: dict[str, Any]) -> str:
    """把文献写成可检索、也可完整还原的分行文本（一条 Memory 即一篇文献）。"""
    lines = [f"标题: {_one_line(doc['title'])}"]
    for label, key in (("作者", "authors"), ("摘要", "abstract"), ("关键词", "keywords"), ("备注", "notes")):
        value = _one_line(doc.get(key))
        if value:
            lines.append(f"{label}: {value}")
    tags = ", ".join(doc.get("tags") or [])
    if tags:
        lines.append(f"标签: {tags}")
    if doc.get("created_at"):
        lines.append(f"时间: {doc['created_at']}")
    return "\n".join(lines)


def _doc_from_text(text: str) -> dict[str, Any] | None:
    """从 Memory 文本还原文献。兼容早期 “ | ” 拼接格式。"""
    doc: dict[str, Any] = {"title": "", "authors": "", "abstract": "", "keywords": "", "notes": "", "tags": []}
    parsed = False
    for line in (text or "").splitlines():
        label, sep, value = line.partition(":")
        key = DOC_LABELS.get(label.strip())
        if not sep or key is None:
            continue
        value = value.strip()
        if key == "tags":
            doc["tags"] = [tag.strip() for tag in value.split(",") if tag.strip()]
        else:
            doc[key] = value
        parsed = True

    if not parsed:
        parts = [part.strip() for part in (text or "").split(" | ")]
        if not parts or not parts[0]:
            return None
        doc["title"] = parts[0]
        for key, value in zip(("authors", "abstract", "keywords"), parts[1:4]):
            doc[key] = value
        if len(parts) > 4:
            doc["tags"] = [tag.strip() for tag in parts[4].split(",") if tag.strip()]

    if not doc["title"]:
        return None
    doc["id"] = hashlib.md5(doc["title"].encode("utf-8")).hexdigest()[:12]
    doc["created_at"] = doc.get("created_at") or ""
    return doc


async def _load_library(pc: PowerContextClient, scope_id: str) -> list[dict[str, Any]]:
    """启动时从 PowerContext 读回全部文献记忆，保证重启后数据仍可见、可检索。"""
    response = await pc.list_memory_entries(ListMemoryEntriesRequest(scope_id=scope_id))
    papers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in response.entries:
        if getattr(entry, "kind", "") != "paper" or getattr(entry, "state", "active") != "active":
            continue
        doc = _doc_from_text(entry.text or "")
        if doc is None or doc["title"] in seen:
            continue
        seen.add(doc["title"])
        papers.append(doc)
    # list_memory_entries 按新到旧返回，这里按导入时间还原原始顺序。
    papers.sort(key=lambda item: item.get("created_at") or "")
    return papers


def _truncate_utf8(text: str, limit: int = 8000) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def _find_paper(text: str) -> dict[str, Any] | None:
    doc = _doc_from_text(text)
    if doc is None:
        return None
    for paper in state["papers"]:
        if paper["id"] == doc["id"]:
            return paper
    return None


def _parse_tags(memory_text: str) -> list[str]:
    payload = memory_text.split(":", 1)[1] if ":" in memory_text else memory_text
    return [t.strip() for t in payload.split(",") if t.strip()]


async def _recall_preferences(user_id: str) -> tuple[list[str], list[str]]:
    """从 PowerContext 读回该用户保存过的偏好记忆（跨进程重启依然有效）。"""
    scope_id = await _user_scope(user_id)
    response = await _pc().list_memory_entries(ListMemoryEntriesRequest(scope_id=scope_id))
    memories = [
        entry.text or ""
        for entry in response.entries
        if getattr(entry, "kind", "") == "preference" and getattr(entry, "state", "active") == "active"
    ]
    tags: list[str] = []
    for memory in memories:
        for tag in _parse_tags(memory):
            if tag not in tags:
                tags.append(tag)
    return memories, tags


def _normalize_scores(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 FTS 原始分数换算成组内相对匹配度（最高分为 100%），便于界面展示。"""
    if not results:
        return results
    top = max(item["score"] for item in results)
    if top <= 0:
        return results
    for item in results:
        item["score"] = round(item["score"] / top, 4)
    return results


# ---------------------------------------------------------------- 文献入库 / 列表


@app.post("/api/documents/import")
async def import_documents(request: Request):
    """把 CSV 中每篇文献写入 PowerContext（每条文献 = 一条 Memory）。"""
    raw = await request.body()
    try:
        # 前端以 JSON 字符串提交 CSV；也兼容直接提交纯文本。
        csv_data = await request.json()
        if not isinstance(csv_data, str):
            raise ValueError("请求体必须是 CSV 字符串")
    except Exception:
        csv_data = raw.decode("utf-8-sig", errors="replace")

    reader = csv.DictReader(io.StringIO(csv_data))
    imported: list[dict[str, Any]] = []
    seen_titles = {p["title"] for p in state["papers"]}

    for row in reader:
        title = (row.get("title") or "").strip()
        if not title or title in seen_titles:
            continue
        tags = [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()]
        doc = {
            "id": hashlib.md5(title.encode("utf-8")).hexdigest()[:12],
            "title": title,
            "authors": (row.get("authors") or "").strip(),
            "abstract": (row.get("abstract") or "").strip(),
            "keywords": (row.get("keywords") or "").strip(),
            "notes": (row.get("notes") or "").strip(),
            "tags": tags,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await _pc().remember_memory(
            RememberMemoryRequest(
                scope_id=state["library_scope"],
                kind="paper",
                text=_truncate_utf8(_memory_text(doc)),
                reason=f"导入文献 {doc['id']}",
            )
        )
        state["papers"].append(doc)
        seen_titles.add(title)
        imported.append(doc)

    return imported


@app.get("/api/documents")
async def list_documents():
    return state["papers"]


# ---------------------------------------------------------------- 检索（PowerContext search_memory）


@app.post("/api/search")
async def search(query: SearchQuery):
    """通过 PowerContext search_memory 检索文献，返回文献 + 匹配度。"""
    hits = await _pc().search_memory(
        SearchMemoryRequest(
            scope_id=state["library_scope"],
            query=query.query,
            limit=max(1, min(query.top_k, 50)),
            mode="fts",
        )
    )
    results = []
    for hit in hits.hits:
        paper = _find_paper(hit.text)
        if paper is None:
            continue
        results.append({"document": paper, "score": float(hit.score)})
    return _normalize_scores(results)


# ---------------------------------------------------------------- 用户偏好记忆


@app.get("/api/user/{user_id}/preferences")
async def get_preferences(user_id: str):
    """从 PowerContext 读回该用户之前保存的偏好。"""
    memories, tags = await _recall_preferences(user_id)
    return {"user_id": user_id, "preferred_tags": tags, "recalled_memories": memories}


@app.post("/api/user/{user_id}/preferences")
async def save_preferences(user_id: str, payload: PreferencePayload):
    """把用户偏好写入该用户在 PowerContext 中的 Scope。"""
    scope_id = await _user_scope(user_id)
    memory = await _pc().remember_memory(
        RememberMemoryRequest(
            scope_id=scope_id,
            kind="preference",
            text=_truncate_utf8("偏好标签: " + ", ".join(payload.preferred_tags)),
            reason="保存用户研究偏好",
        )
    )
    return {
        "status": "ok",
        "user_id": user_id,
        "preferred_tags": payload.preferred_tags,
        "memory": str(getattr(memory, "memory", "")),
    }


@app.get("/api/user/{user_id}/recommendations")
async def recommendations(user_id: str):
    """数据流：读回 PowerContext 中的偏好 Memory -> 提取标签 -> 检索文献。"""
    memories, tags = await _recall_preferences(user_id)
    if not tags:
        return {"based_on": [], "recommendations": []}

    seen: set[str] = set()
    recs: list[dict[str, Any]] = []
    for tag in tags:
        hits = await _pc().search_memory(
            SearchMemoryRequest(scope_id=state["library_scope"], query=tag, limit=5, mode="fts")
        )
        for hit in hits.hits:
            paper = _find_paper(hit.text)
            if paper is None or paper["id"] in seen:
                continue
            seen.add(paper["id"])
            recs.append({"document": paper, "matched_tag": tag, "score": float(hit.score)})
    return {"based_on": memories, "recommendations": _normalize_scores(recs)[:5]}


# ---------------------------------------------------------------- 健康检查 / 证据


@app.get("/health")
async def health():
    caps = await _pc().get_capabilities()
    return {
        "status": "ok",
        "tech": "PowerContext",
        "search_modes": [str(m) for m in caps.search_modes],
        "library_scope": state["library_scope"],
        "papers": len(state["papers"]),
    }


@app.get("/api/health")
async def api_health():
    return await health()


# ---------------------------------------------------------------- 前端页面


if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/app", include_in_schema=False)
    async def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"))


SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data"
if SAMPLE_DIR.is_dir():
    app.mount("/samples", StaticFiles(directory=str(SAMPLE_DIR)), name="samples")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
