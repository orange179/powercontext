"""Research Assistant Backend - 文献整理与知识检索助手

集成 seekdb（语义检索）和 PowerContext（用户记忆）的智能文献管理工具。

生产环境集成：
    from pylibseekdb import SeekDBClient
    from powercontext.client.client import PowerContextClient
    
    seekdb = SeekDBClient(host="...", port=3306, database="...", api_key="...")
    powercontext = PowerContextClient(api_url="...", api_key="...")
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any
import csv
import io
from datetime import datetime
import hashlib

# seekdb 和 PowerContext 集成（生产环境使用真实客户端）
try:
    from pylibseekdb import SeekDBClient
    from powercontext.client.client import PowerContextClient
    USE_REAL_CLIENTS = True
except ImportError:
    USE_REAL_CLIENTS = False

app = FastAPI(title="Research Assistant API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 内存存储（演示用）
documents_db: List[Dict[str, Any]] = []
user_prefs_db: Dict[str, Dict[str, Any]] = {}


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
    return {
        "status": "ok",
        "service": "Research Assistant",
        "integrations": {
            "seekdb": "pylibseekdb" if USE_REAL_CLIENTS else "mock",
            "powercontext": "powercontext.client" if USE_REAL_CLIENTS else "mock"
        }
    }


@app.post("/api/import")
async def import_documents(csv_data: str):
    """导入文献（seekdb 集成点）"""
    reader = csv.DictReader(io.StringIO(csv_data))
    docs = []
    for row in reader:
        doc = {
            "id": hashlib.md5(row["title"].encode()).hexdigest()[:12],
            "title": row["title"],
            "authors": row.get("authors", ""),
            "abstract": row.get("abstract", ""),
            "keywords": row.get("keywords", ""),
            "tags": [t.strip() for t in row.get("tags", "").split(",") if t.strip()],
            "created_at": datetime.now().isoformat()
        }
        documents_db.append(doc)
        docs.append(doc)
        
        # 生产环境：seekdb.insert("papers", doc)
    
    return {"imported": len(docs), "total": len(documents_db)}


@app.get("/api/documents")
async def list_documents():
    """列出所有文献"""
    return {"documents": documents_db, "count": len(documents_db)}


@app.post("/api/search")
async def search(query: SearchQuery):
    """语义检索（seekdb 集成点）"""
    query_lower = query.query.lower()
    results = []
    
    for doc in documents_db:
        score = 0
        if query_lower in doc["title"].lower():
            score += 3
        if query_lower in doc["abstract"].lower():
            score += 2
        if query_lower in doc["keywords"].lower():
            score += 1
        for tag in doc["tags"]:
            if query_lower in tag.lower():
                score += 1
        
        if score > 0:
            results.append({"document": doc, "score": score})
    
    results.sort(key=lambda x: x["score"], reverse=True)
    
    # 生产环境：results = seekdb.search("papers", query.query, top_k=query.top_k)
    
    return {"results": results[:query.top_k]}


@app.get("/api/user/{user_id}/prefs")
async def get_prefs(user_id: str):
    """获取用户偏好（PowerContext 集成点）"""
    prefs = user_prefs_db.get(user_id, {"preferred_tags": [], "reading_progress": {}})
    
    # 生产环境：prefs = powercontext.get(user_id, "preferences")
    
    return {"user_id": user_id, "preferences": prefs}


@app.post("/api/user/{user_id}/prefs")
async def save_prefs(user_id: str, prefs: Dict[str, Any]):
    """保存用户偏好（PowerContext 集成点）"""
    user_prefs_db[user_id] = prefs
    
    # 生产环境：powercontext.set(user_id, "preferences", prefs)
    
    return {"status": "ok", "message": "偏好已保存"}


@app.get("/api/user/{user_id}/recommendations")
async def get_recommendations(user_id: str):
    """基于用户偏好推荐文献（seekdb + PowerContext 协同）"""
    prefs = user_prefs_db.get(user_id, {})
    preferred_tags = prefs.get("preferred_tags", [])
    
    if not preferred_tags:
        return {"recommendations": [], "message": "请先设置偏好"}
    
    recommendations = []
    for doc in documents_db:
        score = sum(1 for tag in doc["tags"] if tag in preferred_tags)
        if score > 0:
            recommendations.append({
                "document": doc,
                "relevance_score": score,
                "reason": f"匹配 {score} 个偏好标签"
            })
    
    recommendations.sort(key=lambda x: x["relevance_score"], reverse=True)
    
    # 生产环境：
    # prefs = powercontext.get(user_id, "preferences")
    # results = seekdb.search("papers", filter={"tags": {"$in": prefs["preferred_tags"]}})
    
    return {"recommendations": recommendations[:5]}
