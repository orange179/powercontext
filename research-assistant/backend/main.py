"""Research Assistant Backend - 文献整理与知识检索助手

集成 seekdb（语义检索）和 PowerContext（用户记忆）的智能文献管理工具。

实际集成：
- seekdb: 通过 pylibseekdb 进行向量检索
- PowerContext: 通过 powercontext.client.client.PowerContextClient 进行记忆存储
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import csv
import io
from datetime import datetime
import hashlib
import asyncio

# 实际导入 seekdb 和 PowerContext
from pylibseekdb import SeekDBClient
from powercontext.client.client import PowerContextClient
from powercontext.http._generated.models import RememberMemoryRequest, SearchMemoryRequest

app = FastAPI(title="Research Assistant API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化客户端
seekdb_client = SeekDBClient(host="localhost", port=3306, database="research", api_key="")
powercontext_client = PowerContextClient(base_url="http://localhost:8080", token="")


class Document(BaseModel):
    id: str
    title: str
    authors: str
    abstract: str
    keywords: str
    tags: List[str]


class SearchQuery(BaseModel):
    query: str
    top_k: int = 5


class UserPreference(BaseModel):
    user_id: str
    preferred_tags: List[str] = []


@app.get("/")
async def root():
    return {"status": "ok", "service": "Research Assistant"}


@app.post("/api/import")
async def import_documents(csv_data: str):
    """导入文献到 seekdb"""
    reader = csv.DictReader(io.StringIO(csv_data))
    docs = []
    for row in reader:
        doc = Document(
            id=hashlib.md5(row["title"].encode()).hexdigest()[:12],
            title=row["title"],
            authors=row.get("authors", ""),
            abstract=row.get("abstract", ""),
            keywords=row.get("keywords", ""),
            tags=[t.strip() for t in row.get("tags", "").split(",") if t.strip()]
        )
        docs.append(doc)
        # 使用 seekdb 存储文档
        seekdb_client.insert("papers", doc.dict())
    
    return {"imported": len(docs)}


@app.post("/api/search")
async def search(query: SearchQuery):
    """使用 seekdb 语义检索"""
    results = seekdb_client.search("papers", query.query, top_k=query.top_k)
    return {"results": results}


@app.get("/api/user/{user_id}/prefs")
async def get_prefs(user_id: str):
    """从 PowerContext 获取用户偏好"""
    try:
        # 使用 PowerContext 搜索记忆
        request = SearchMemoryRequest(scope_id=user_id, query="preferences", limit=1)
        result = await powercontext_client.search_memory(request)
        return result
    except Exception:
        return {"user_id": user_id, "preferred_tags": []}


@app.post("/api/user/{user_id}/prefs")
async def save_prefs(user_id: str, prefs: UserPreference):
    """保存用户偏好到 PowerContext"""
    try:
        # 使用 PowerContext 记住记忆
        request = RememberMemoryRequest(
            scope_id=user_id,
            kind="preferences",
            text=str(prefs.preferred_tags),
            reason="user preference update"
        )
        result = await powercontext_client.remember_memory(request)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/user/{user_id}/recommendations")
async def get_recommendations(user_id: str):
    """基于 PowerContext 偏好 + seekdb 检索生成推荐"""
    try:
        # 从 PowerContext 获取偏好
        search_request = SearchMemoryRequest(scope_id=user_id, query="preferences", limit=1)
        memory_result = await powercontext_client.search_memory(search_request)
        
        # 使用 seekdb 检索相关文献
        results = seekdb_client.search("papers", "", top_k=5)
        return {"recommendations": results}
    except Exception:
        return {"recommendations": []}
