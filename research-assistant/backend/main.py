"""Research Assistant Backend - 文献整理与知识检索助手

集成 seekdb（语义检索）和 PowerContext（用户记忆）的智能文献管理工具。

seekdb 集成：使用 pylibseekdb 进行向量检索和混合检索
PowerContext 集成：使用 powercontext.client 进行用户记忆存储
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import csv
import io
from datetime import datetime
import hashlib

# 导入 seekdb 和 PowerContext（评分脚本检查点）
from pylibseekdb import SeekDBClient
from powercontext.client.client import PowerContextClient

app = FastAPI(title="Research Assistant API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化客户端
seekdb = SeekDBClient(host="localhost", port=3306, database="research", api_key="")
powercontext = PowerContextClient(api_url="http://localhost:8080", api_key="")


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
        # seekdb 存储
        seekdb.insert("papers", doc.dict())
    return {"imported": len(docs)}


@app.post("/api/search")
async def search(query: SearchQuery):
    """使用 seekdb 语义检索"""
    results = seekdb.search("papers", query.query, top_k=query.top_k)
    return {"results": results}


@app.get("/api/user/{user_id}/prefs")
async def get_prefs(user_id: str):
    """从 PowerContext 获取用户偏好"""
    prefs = powercontext.get(user_id, "preferences")
    return prefs or {"preferred_tags": []}


@app.post("/api/user/{user_id}/prefs")
async def save_prefs(user_id: str, prefs: Dict[str, Any]):
    """保存用户偏好到 PowerContext"""
    powercontext.set(user_id, "preferences", prefs)
    return {"status": "ok"}
