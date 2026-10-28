"""Research Assistant Backend - 文献整理与知识检索助手"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import csv
import io
import json
from datetime import datetime
import hashlib

app = FastAPI(title="Research Assistant API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 模拟数据库
documents_db = []
user_preferences_db = {}
search_history_db = []


class Document(BaseModel):
    id: str
    title: str
    authors: str
    abstract: str
    keywords: str
    notes: str
    tags: List[str]
    created_at: str


class SearchQuery(BaseModel):
    query: str
    top_k: int = 5


class UserPreference(BaseModel):
    user_id: str
    preferred_tags: List[str] = []
    reading_progress: dict = {}
    search_history: List[str] = []


class SearchResult(BaseModel):
    document: Document
    score: float
    matched_keywords: List[str]


@app.get("/")
async def root():
    return {"message": "Research Assistant API", "version": "1.0.0"}


@app.post("/api/documents/import", response_model=List[Document])
async def import_documents(csv_content: str):
    """导入 CSV 格式的文献数据"""
    try:
        reader = csv.DictReader(io.StringIO(csv_content))
        imported = []
        
        for row in reader:
            doc_id = hashlib.md5(f"{row.get('title', '')}{row.get('authors', '')}".encode()).hexdigest()[:12]
            
            doc = Document(
                id=doc_id,
                title=row.get("title", ""),
                authors=row.get("authors", ""),
                abstract=row.get("abstract", ""),
                keywords=row.get("keywords", ""),
                notes=row.get("notes", ""),
                tags=[t.strip() for t in row.get("tags", "").split(",") if t.strip()],
                created_at=datetime.now().isoformat()
            )
            documents_db.append(doc)
            imported.append(doc)
        
        return imported
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"导入失败: {str(e)}")


@app.get("/api/documents", response_model=List[Document])
async def list_documents():
    """列出所有文献"""
    return documents_db


@app.post("/api/search", response_model=List[SearchResult])
async def search_documents(query: SearchQuery):
    """语义检索文献（模拟 seekdb 集成）"""
    query_text = query.query.lower()
    results = []
    
    for doc in documents_db:
        score = 0.0
        matched = []
        
        # 简单的关键词匹配（实际应使用 seekdb 的向量检索）
        if query_text in doc.title.lower():
            score += 0.4
            matched.append("title")
        if query_text in doc.abstract.lower():
            score += 0.3
            matched.append("abstract")
        if query_text in doc.keywords.lower():
            score += 0.2
            matched.append("keywords")
        
        # 标签匹配
        for tag in doc.tags:
            if query_text in tag.lower():
                score += 0.1
                matched.append(f"tag:{tag}")
        
        if score > 0:
            results.append(SearchResult(
                document=doc,
                score=score,
                matched_keywords=matched
            ))
    
    # 按分数排序
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:query.top_k]


@app.get("/api/user/{user_id}/preferences", response_model=UserPreference)
async def get_user_preferences(user_id: str):
    """获取用户偏好（PowerContext 集成）"""
    if user_id not in user_preferences_db:
        user_preferences_db[user_id] = UserPreference(user_id=user_id)
    return user_preferences_db[user_id]


@app.post("/api/user/{user_id}/preferences", response_model=UserPreference)
async def update_user_preferences(user_id: str, preferences: UserPreference):
    """更新用户偏好（PowerContext 集成）"""
    user_preferences_db[user_id] = preferences
    return preferences


@app.post("/api/user/{user_id}/progress")
async def update_reading_progress(user_id: str, document_id: str, progress: dict):
    """更新阅读进度（PowerContext 记忆存储）"""
    if user_id not in user_preferences_db:
        user_preferences_db[user_id] = UserPreference(user_id=user_id)
    
    user_preferences_db[user_id].reading_progress[document_id] = {
        **progress,
        "updated_at": datetime.now().isoformat()
    }
    
    return {"status": "success", "message": "进度已保存"}


@app.get("/api/user/{user_id}/recommendations")
async def get_recommendations(user_id: str):
    """基于用户偏好推荐文献（PowerContext + seekdb 协同）"""
    if user_id not in user_preferences_db:
        return {"recommendations": [], "message": "暂无推荐，请先设置偏好"}
    
    prefs = user_preferences_db[user_id]
    recommendations = []
    
    # 基于标签推荐
    for doc in documents_db:
        relevance_score = 0
        for tag in doc.tags:
            if tag in prefs.preferred_tags:
                relevance_score += 1
        
        if relevance_score > 0:
            recommendations.append({
                "document": doc,
                "relevance_score": relevance_score,
                "reason": f"匹配 {relevance_score} 个偏好标签"
            })
    
    recommendations.sort(key=lambda x: x["relevance_score"], reverse=True)
    return {"recommendations": recommendations[:5]}


# 挂载静态文件
import os
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")
    
    @app.get("/app")
    async def serve_frontend():
        return FileResponse(os.path.join(frontend_path, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
