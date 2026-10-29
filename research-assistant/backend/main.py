"""Research Assistant Backend - 文献整理与知识检索助手

集成 seekdb（语义检索）和 PowerContext（用户记忆）的智能文献管理工具。
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import csv
import io
import json
from datetime import datetime
import hashlib
import os

# 尝试导入真实的 seekdb 和 PowerContext 客户端
try:
    from pylibseekdb import SeekDBClient as RealSeekDBClient
    SEEKDB_AVAILABLE = True
except ImportError:
    SEEKDB_AVAILABLE = False

try:
    from powercontext.client.client import PowerContextClient as RealPowerContextClient
    POWERCONTEXT_AVAILABLE = True
except ImportError:
    POWERCONTEXT_AVAILABLE = False

app = FastAPI(title="Research Assistant API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# seekdb 集成 - 语义检索客户端
# ============================================================================
# 实际使用时：from pylibseekdb import SeekDBClient
# pylibseekdb 仅在 Linux/macOS 可用，Windows 使用演示实现

class SeekDBClient:
    """seekdb 向量检索客户端
    
    生产环境 API:
        client = SeekDBClient(host="...", port=3306, database="...", api_key="...")
        results = client.vector_search(collection="papers", query_vector=embed(query), top_k=5)
        results = client.hybrid_search(collection="papers", vector_query=..., text_query=..., filter={...})
    """
    
    def __init__(self):
        self.collections = {}
    
    def create_collection(self, name: str, schema: Dict[str, Any]):
        """创建文档集合"""
        self.collections[name] = {"schema": schema, "documents": []}
    
    def insert_document(self, collection: str, doc: Dict[str, Any]):
        """插入文档到集合"""
        if collection not in self.collections:
            self.create_collection(collection, {})
        self.collections[collection]["documents"].append(doc)
    
    def vector_search(self, collection: str, query: str, top_k: int = 5) -> List[Dict]:
        """向量语义检索
        
        生产环境: results = client.vector_search(collection="papers", query_vector=embed(query), top_k=5)
        """
        if collection not in self.collections:
            return []
        query_lower = query.lower()
        results = []
        for doc in self.collections[collection]["documents"]:
            score = 0.0
            matched_fields = []
            if query_lower in doc.get("title", "").lower():
                score += 0.4
                matched_fields.append("title")
            if query_lower in doc.get("abstract", "").lower():
                score += 0.3
                matched_fields.append("abstract")
            if query_lower in doc.get("keywords", "").lower():
                score += 0.2
                matched_fields.append("keywords")
            for tag in doc.get("tags", []):
                if query_lower in tag.lower():
                    score += 0.1
                    matched_fields.append(f"tag:{tag}")
            if score > 0:
                results.append({"document": doc, "score": score, "matched_fields": matched_fields})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    
    def hybrid_search(self, collection: str, query: str, filters: Dict = None, top_k: int = 5) -> List[Dict]:
        """混合检索（向量 + 全文 + 结构化过滤）
        
        生产环境: results = client.hybrid_search(collection="papers", vector_query=..., text_query=..., filter={...})
        """
        results = self.vector_search(collection, query, top_k)
        if filters:
            filtered = []
            for result in results:
                doc = result["document"]
                match = True
                for key, value in filters.items():
                    if key == "tags" and "$in" in value:
                        if not any(tag in value["$in"] for tag in doc.get("tags", [])):
                            match = False
                if match:
                    filtered.append(result)
            return filtered
        return results


# ============================================================================
# PowerContext 集成 - 用户记忆客户端
# ============================================================================
# 实际使用时：from powercontext.client import PowerContextClient

class PowerContextClient:
    """PowerContext 用户记忆客户端
    
    生产环境 API:
        client = PowerContextClient(api_url="...", api_key="...")
        client.set_memory(user_id="...", key="preferences", value={...})
        memory = client.get_memory(user_id="...", key="preferences")
        client.delete_memory(user_id="...", key="...")
    """
    
    def __init__(self):
        self.memories = {}
    
    def set_memory(self, user_id: str, key: str, value: Any):
        """保存用户记忆"""
        if user_id not in self.memories:
            self.memories[user_id] = {}
        self.memories[user_id][key] = {"value": value, "updated_at": datetime.now().isoformat()}
    
    def get_memory(self, user_id: str, key: str) -> Optional[Any]:
        """读取用户记忆"""
        if user_id in self.memories and key in self.memories[user_id]:
            return self.memories[user_id][key]["value"]
        return None
    
    def delete_memory(self, user_id: str, key: str):
        """删除用户记忆"""
        if user_id in self.memories and key in self.memories[user_id]:
            del self.memories[user_id][key]
    
    def list_memories(self, user_id: str) -> List[str]:
        """列出用户所有记忆键"""
        if user_id in self.memories:
            return list(self.memories[user_id].keys())
        return []


# 初始化客户端（优先使用真实客户端，失败时降级到模拟实现）
def init_seekdb_client():
    if SEEKDB_AVAILABLE:
        try:
            client = RealSeekDBClient(
                host=os.getenv("SEEKDB_HOST", "localhost"),
                port=int(os.getenv("SEEKDB_PORT", 3306)),
                database=os.getenv("SEEKDB_DATABASE", "research_db"),
                api_key=os.getenv("SEEKDB_API_KEY")
            )
            return client
        except Exception as e:
            print(f"seekdb 连接失败，使用模拟实现：{e}")
    return MockSeekDBClient()

def init_powercontext_client():
    if POWERCONTEXT_AVAILABLE:
        try:
            client = RealPowerContextClient(
                api_url=os.getenv("POWERCONTEXT_API_URL", "http://localhost:8080"),
                api_key=os.getenv("POWERCONTEXT_API_KEY")
            )
            return client
        except Exception as e:
            print(f"PowerContext 连接失败，使用模拟实现：{e}")
    return MockPowerContextClient()

seekdb_client = init_seekdb_client()
powercontext_client = init_powercontext_client()

# 创建文献集合
seekdb_client.create_collection("papers", {
    "title": "string",
    "authors": "string",
    "abstract": "string",
    "keywords": "string",
    "tags": "list[string]",
    "created_at": "datetime"
})


# ============================================================================
# 数据模型
# ============================================================================

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
    filters: Optional[Dict[str, Any]] = None


class UserPreference(BaseModel):
    user_id: str
    preferred_tags: List[str] = []
    reading_progress: Dict[str, Any] = {}
    search_history: List[str] = []


class SearchResult(BaseModel):
    document: Document
    score: float
    matched_keywords: List[str]


# ============================================================================
# API 端点
# ============================================================================

@app.get("/")
async def root():
    return {
        "message": "Research Assistant API",
        "version": "1.0.0",
        "integrations": {
            "seekdb": "语义检索服务",
            "powercontext": "用户记忆服务"
        }
    }


@app.post("/api/documents/import", response_model=List[Document])
async def import_documents(csv_content: str):
    """导入 CSV 格式的文献数据到 seekdb"""
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
            
            # 存储到 seekdb
            seekdb_client.insert_document("papers", doc.dict())
            imported.append(doc)
        
        return imported
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"导入失败：{str(e)}")


@app.get("/api/documents", response_model=List[Document])
async def list_documents():
    """列出所有文献（从 seekdb 检索）"""
    results = seekdb_client.vector_search("papers", "", top_k=1000)
    return [Document(**r["document"]) for r in results]


@app.post("/api/search", response_model=List[SearchResult])
async def search_documents(query: SearchQuery):
    """使用 seekdb 进行语义检索"""
    results = seekdb_client.hybrid_search(
        collection="papers",
        query=query.query,
        filters=query.filters,
        top_k=query.top_k
    )
    
    return [
        SearchResult(
            document=Document(**r["document"]),
            score=r["score"],
            matched_keywords=r["matched_fields"]
        )
        for r in results
    ]


@app.get("/api/user/{user_id}/preferences", response_model=UserPreference)
async def get_user_preferences(user_id: str):
    """从 PowerContext 获取用户偏好"""
    prefs = powercontext_client.get_memory(user_id, "preferences")
    
    if prefs is None:
        default_prefs = UserPreference(user_id=user_id)
        powercontext_client.set_memory(user_id, "preferences", default_prefs.dict())
        return default_prefs
    
    return UserPreference(**prefs)


@app.post("/api/user/{user_id}/preferences", response_model=UserPreference)
async def update_user_preferences(user_id: str, preferences: UserPreference):
    """保存用户偏好到 PowerContext"""
    powercontext_client.set_memory(user_id, "preferences", preferences.dict())
    return preferences


@app.post("/api/user/{user_id}/progress")
async def update_reading_progress(user_id: str, document_id: str, progress: Dict[str, Any]):
    """保存阅读进度到 PowerContext"""
    current_progress = powercontext_client.get_memory(user_id, "reading_progress") or {}
    current_progress[document_id] = {
        **progress,
        "updated_at": datetime.now().isoformat()
    }
    powercontext_client.set_memory(user_id, "reading_progress", current_progress)
    
    return {"status": "success", "message": "进度已保存到 PowerContext"}


@app.get("/api/user/{user_id}/recommendations")
async def get_recommendations(user_id: str):
    """基于 PowerContext 用户偏好 + seekdb 检索生成推荐"""
    prefs = powercontext_client.get_memory(user_id, "preferences")
    
    if prefs is None:
        return {"recommendations": [], "message": "暂无推荐，请先设置偏好"}
    
    pref_data = UserPreference(**prefs)
    
    if not pref_data.preferred_tags:
        return {"recommendations": [], "message": "请先选择感兴趣的研究标签"}
    
    recommendations = []
    all_docs = seekdb_client.vector_search("papers", "", top_k=1000)
    
    for result in all_docs:
        doc = result["document"]
        relevance_score = sum(1 for tag in doc.get("tags", []) if tag in pref_data.preferred_tags)
        
        if relevance_score > 0:
            recommendations.append({
                "document": doc,
                "relevance_score": relevance_score,
                "reason": f"匹配 {relevance_score} 个偏好标签"
            })
    
    recommendations.sort(key=lambda x: x["relevance_score"], reverse=True)
    return {"recommendations": recommendations[:5]}


@app.delete("/api/user/{user_id}/memory/{key}")
async def delete_user_memory(user_id: str, key: str):
    """删除用户记忆（PowerContext）"""
    powercontext_client.delete_memory(user_id, key)
    return {"status": "success", "message": f"记忆 {key} 已删除"}


@app.get("/api/user/{user_id}/memories")
async def list_user_memories(user_id: str):
    """列出用户所有记忆键（PowerContext）"""
    keys = powercontext_client.list_memories(user_id)
    return {"user_id": user_id, "memory_keys": keys}


# ============================================================================
# 静态文件服务
# ============================================================================

frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")
    
    @app.get("/app")
    async def serve_frontend():
        return FileResponse(os.path.join(frontend_path, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
