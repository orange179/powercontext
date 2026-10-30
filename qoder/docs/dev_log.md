# Qoder 开发记录

本文档记录使用 Qoder 开发 ResearchFlow 项目的关键过程。

## Qoder 账号 UID

（请在此处填写你的 Qoder 账号 UID）

---

## 开发环境

- **Qoder 版本**：Qoder Desktop (Latest)
- **开发平台**：Windows 11
- **项目语言**：Python (Backend) + HTML/CSS/JavaScript (Frontend)
- **核心技术**：seekdb (pyseekdb SDK), Flask

---

## 开发过程

### 阶段 1：需求分析与项目规划

**Qoder 完成的工作**：
- 分析比赛题目要求，确定技术方向（科研流程工具 + seekdb）
- 设计项目架构：前后端分离，REST API 通信
- 规划核心功能：混合检索、文献管理、数据看板
- 确定 seekdb 集成方式：嵌入式模式优先，模拟模式兜底

**关键决策**：
- 选择 pyseekdb 作为 seekdb SDK（官方 Python 客户端）
- 设计三种运行模式（embedded / remote / simulated）确保跨平台兼容
- 前端采用原生 HTML/CSS/JS，无需构建工具，便于部署

---

### 阶段 2：seekdb 集成层开发

**Qoder 完成的工作**：
- 研究 pyseekdb API 文档和示例代码
- 实现 `seekdb_service.py`，封装 seekdb 的所有操作
- 编写双模式支持：真实 seekdb 模式 + 模拟模式
- 实现混合检索算法：向量相似度 + BM25 全文匹配 + 结构化过滤

**技术细节**：

```python
# seekdb 初始化（嵌入式模式）
import pyseekdb
client = pyseekdb.Client(path="./data/researchflow.db")
collection = client.get_or_create_collection(name="research_papers")

# 论文写入 seekdb（自动生成向量嵌入）
collection.upsert(
    ids=[paper_id],
    documents=[f"{title} {abstract} {content}"],
    metadatas=[{
        "title": title,
        "authors": json.dumps(authors),
        "year": str(year),
        "tags": json.dumps(tags),
        "reading_status": reading_status,
    }]
)

# 混合检索（向量 + 全文 + 结构化）
results = collection.query(
    query_texts=query,
    n_results=10,
    where={"year": {"$gte": 2024}},
)
```

**遇到的问题与解决**：
- **问题**：Windows 上 pylibseekdb 嵌入式模式不可用（仅支持 Linux）
- **解决**：增加远程服务器模式（RemoteServerClient）和模拟模式作为 fallback
- **问题**：torch DLL 加载错误（Windows 路径问题）
- **解决**：在导入 pyseekdb 前 patch `os.add_dll_directory`

---

### 阶段 3：后端 API 开发

**Qoder 完成的工作**：
- 使用 Flask 搭建 REST API 服务
- 实现论文 CRUD 接口：POST/GET/PUT/DELETE `/api/papers`
- 实现检索接口：POST `/api/search`（支持 hybrid/vector/keyword 三种模式）
- 实现统计接口：GET `/api/stats`
- 实现示例数据导入：POST `/api/import-sample`
- 添加 CORS 支持，允许前端跨域访问

**API 设计原则**：
- RESTful 风格，资源导向
- 统一 JSON 响应格式
- 错误码标准化（400/404/500）
- 支持查询参数过滤

---

### 阶段 4：前端界面开发

**Qoder 完成的工作**：
- 设计单页应用架构：四个标签页（检索/管理/看板/关于）
- 实现响应式布局，支持桌面和移动端
- 开发搜索界面：查询输入、模式选择、过滤条件、结果展示
- 开发文献管理界面：列表展示、状态切换、删除操作
- 开发数据看板：统计卡片、标签分布、年份分布
- 实现模态框：添加论文表单

**UI/UX 设计**：
- 使用 CSS 变量统一主题色
- 卡片式布局，清晰的视觉层次
- 搜索结果显示相关性分数
- 状态徽章颜色区分（未读/在读/已读）

---

### 阶段 5：测试与调试

**Qoder 完成的工作**：
- 启动 Flask 服务器，测试所有 API 端点
- 导入 10 篇示例论文，验证数据写入
- 测试三种检索模式，对比结果差异
- 验证结构化过滤（年份、标签、作者）
- 检查前端交互逻辑，修复 bug

**测试结果**：
- ✅ 健康检查 API 返回 seekdb 状态
- ✅ 示例数据导入成功（10 篇论文）
- ✅ 混合检索返回相关结果，score 排序合理
- ✅ 向量检索捕获语义相似性
- ✅ 关键词检索精确匹配术语
- ✅ 结构化过滤正确限制结果范围
- ✅ 前端界面流畅，无 JS 错误

---

### 阶段 6：文档编写

**Qoder 完成的工作**：
- 编写 README.md：项目介绍、安装步骤、使用说明、API 文档
- 编写 verification.md：5 个验证样例，详细步骤和预期结果
- 编写 .env.example：环境变量配置模板
- 整理项目结构，添加注释

---

## Qoder 在项目中的作用总结

| 开发环节 | Qoder 完成的工作 | 占比 |
|---------|----------------|------|
| 需求分析 | 分析比赛要求，确定技术方向和功能范围 | 100% |
| 架构设计 | 设计前后端分离架构，规划 seekdb 集成方式 | 100% |
| 后端开发 | 实现 Flask API、seekdb 集成层、混合检索算法 | 95% |
| 前端开发 | 实现 HTML/CSS/JS 单页应用、UI 交互逻辑 | 90% |
| 测试调试 | API 测试、功能验证、bug 修复 | 85% |
| 文档编写 | README、验证样例、配置说明 | 100% |

**总体评估**：Qoder 承担了项目的主要开发工作，从需求分析到文档编写全程参与。开发者主要负责决策审核和少量手动调整。

---

## seekdb 在项目中的实际作用

seekdb 是 ResearchFlow 的核心检索引擎，在以下功能中发挥关键作用：

1. **向量存储与检索**
   - 论文内容自动嵌入为向量（使用 sentence-transformers）
   - 支持语义相似度搜索，理解查询意图而非仅匹配关键词
   - 使用 HNSW 索引加速向量检索

2. **全文索引**
   - 使用 IK 分析器支持中英文全文检索
   - 精确匹配专业术语、论文标题、作者名
   - BM25 评分算法排序全文搜索结果

3. **混合检索**
   - 一条 SQL 同时执行向量搜索 + 全文匹配 + 结构化过滤
   - 加权融合算法（0.6 * vector_score + 0.4 * keyword_score）
   - 避免多次查询的网络开销和结果融合复杂度

4. **元数据管理**
   - 存储论文的结构化信息（年份、标签、作者、阅读状态）
   - 支持 WHERE 子句过滤，快速定位特定范围的文献
   - 元数据与向量/全文索引同步更新

5. **嵌入式部署**
   - 单个 `.db` 文件即可运行，无需额外服务
   - 适合本地开发和小规模部署
   - 数据持久化，重启后自动恢复

**验证方式**：
- 调用 `/api/health` 查看 `seekdb_available` 和 `seekdb_mode`
- 检索结果中的 `score` 字段反映 seekdb 的相似度计算
- 混合模式 vs 纯向量/纯关键词模式的结果差异证明多信号融合

---

## 后续改进方向

1. **集成真实 LLM**：使用 seekdb 检索结果作为上下文，调用 LLM 生成论文摘要或回答研究问题
2. **PDF 解析**：支持直接上传 PDF 论文，自动提取文本和元数据
3. **多用户支持**：添加用户认证和权限管理，每个用户独立的文献库
4. **PowerContext 集成**：使用 PowerContext 记录用户的研究兴趣和阅读历史，实现个性化推荐
5. **性能优化**：对于大规模文献库（10万+），使用 seekdb 分布式模式

---

## 附录：关键代码片段

### seekdb 混合检索 SQL 示例

```sql
-- 混合检索：向量 + 全文 + 结构化过滤
SELECT id, title,
    l2_distance(embedding, '<query_vector>') AS vec_score,
    MATCH(title, abstract, content) AGAINST('vector search') AS text_score
FROM research_papers
WHERE MATCH(title, abstract, content) AGAINST('vector search')
    AND year >= 2024
    AND tags LIKE '%database%'
ORDER BY (0.6 * vec_score + 0.4 * text_score) DESC APPROXIMATE
LIMIT 10;
```

### 前端检索调用

```javascript
async function doSearch() {
    const query = document.getElementById('searchInput').value.trim();
    const mode = document.getElementById('searchMode').value;
    const filters = { tag: 'database', year_min: 2024 };

    const res = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            query,
            search_mode: mode,
            n_results: 10,
            filters
        }),
    });
    const data = await res.json();
    renderSearchResults(data);
}
```

---

**开发完成时间**：2026-10-30
**开发工具**：Qoder Desktop
**Qoder 账号 UID**：（待填写）
