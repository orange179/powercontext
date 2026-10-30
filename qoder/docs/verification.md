# 验证样例

本文档提供可按步骤执行的验证样例，展示 seekdb 在项目中的实际作用。

## 前置条件

1. 已按 README.md 完成安装和启动
2. 应用运行在 http://localhost:5000
3. seekdb 模式显示为 `embedded`、`remote` 或 `simulated`

---

## 样例 1：导入示例数据并验证 seekdb 存储

### 步骤

1. 启动应用后，打开浏览器访问 http://localhost:5000
2. 点击右上角状态指示器，确认 seekdb 模式
3. 进入「文献管理」标签页
4. 点击「导入示例数据」按钮

### 预期结果

- 状态栏显示 `seekdb: embedded` 或 `seekdb: remote` 或 `mode: simulated`
- 导入成功后显示 "Imported 10 papers"
- 文献列表显示 10 篇论文

### seekdb 作用验证

**嵌入式/远程模式**：调用 `/api/health` 确认 `seekdb_available: true`

```bash
curl http://localhost:5000/api/health
# {"seekdb_available": true, "seekdb_mode": "embedded", "status": "ok"}
```

论文数据已通过 `pyseekdb.Collection.upsert()` 写入 seekdb，自动生成向量嵌入并存入向量索引。

**模拟模式**：`seekdb_available: false`，`seekdb_mode: simulated`。数据存储在内存中，使用与 seekdb 相同的 API 模式（upsert/query），便于在无 seekdb 环境下演示。

---

## 样例 2：混合检索 - 向量 + 关键词 + 结构化过滤

### 初始数据

使用样例 1 导入的 10 篇示例论文。

### 操作步骤

1. 进入「智能检索」标签页
2. 在搜索框输入：`vector search hybrid retrieval`
3. 检索模式选择「混合检索 (向量 + 关键词)」
4. 在标签过滤中输入：`database`
5. 点击「检索」

### 预期结果

返回结果中：
- 排名第 1：「Full-Text Search in AI Databases: Beyond BM25」（score ≈ 2.5）
  - 标签包含 "full-text search", "hybrid retrieval"
  - 内容涉及 vector search + full-text + structured filters
- 排名第 2：「Retrieval-Augmented Generation for Scientific Literature」（score ≈ 2.4）
  - 涉及 hybrid retrieval + vector + keyword
- 其他结果按相关性排序

### seekdb 作用验证

混合检索通过 seekdb 的单条 SQL 完成：

```sql
SELECT id, title,
    l2_distance(embedding, '<query_vector>') AS vec_score,
    MATCH(title, abstract, content) AGAINST('vector search hybrid retrieval') AS text_score
FROM research_papers
WHERE tags LIKE '%database%'
ORDER BY (0.6 * vec_score + 0.4 * text_score) DESC APPROXIMATE
LIMIT 10;
```

向量搜索捕获语义相似性（"retrieval" 与 "search" 的语义关联），全文匹配捕获精确术语（"vector", "hybrid"），结构化过滤限制标签范围。

---

## 样例 3：对比不同检索模式的效果

### 操作步骤

使用相同查询 `OceanBase distributed database performance`，分别用三种模式检索：

1. **语义向量检索**
   - 结果侧重于语义相关：可能返回关于 "distributed database" 和 "scalability" 的论文
   - 即使没有精确匹配 "OceanBase"，也能找到语义相近的内容

2. **关键词全文检索**
   - 结果侧重于精确术语匹配：返回包含 "OceanBase"、"distributed"、"performance" 的论文
   - 标题中出现关键词的论文获得更高分数（title boost）

3. **混合检索**
   - 综合两种模式的优势
   - 返回既语义相关又包含关键词的论文

### 预期结果

| 模式 | 排名第 1 | Score | 特点 |
|------|---------|-------|------|
| Vector | Distributed Database Challenges in the AI Era | ~0.7 | 语义理解 |
| Keyword | OceanBase seekdb: An AI-Native Search Database | ~3.0 | 精确匹配 |
| Hybrid | OceanBase seekdb / Distributed Database... | ~2.0 | 综合排序 |

### seekdb 作用验证

三种模式共享同一个 seekdb 查询管道：
- 向量模式：`l2_distance(embedding, query_vec) ORDER BY dist APPROXIMATE`
- 关键词模式：`MATCH(content) AGAINST('query') ORDER BY score`
- 混合模式：两者融合，`0.6 * vec_score + 0.4 * kw_score`

---

## 样例 4：文献管理与状态追踪

### 操作步骤

1. 进入「文献管理」标签页
2. 找到「Experiment Tracking with Structured Knowledge Bases」
3. 点击右侧循环按钮切换状态：unread → reading → read
4. 在顶部筛选器选择「已读」

### 预期结果

- 状态徽章颜色变化：黄色(Unread) → 蓝色(Reading) → 绿色(Read)
- 筛选后仅显示状态为「已读」的论文

### seekdb 作用验证

状态更新通过 `Collection.upsert()` 更新 seekdb 中的 metadata：

```python
collection.upsert(
    ids=[paper_id],
    documents=[doc_text],
    metadatas=[{"reading_status": "read", ...}]
)
```

结构化过滤通过 seekdb 的 SQL WHERE 子句实现。

---

## 样例 5：API 直接调用验证

### 使用 curl 验证 seekdb 集成

```bash
# 1. 健康检查
curl http://localhost:5000/api/health

# 2. 导入示例数据
curl -X POST http://localhost:5000/api/import-sample

# 3. 混合检索
curl -X POST http://localhost:5000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"向量检索与混合搜索","search_mode":"hybrid","n_results":5}'

# 4. 仅向量检索
curl -X POST http://localhost:5000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"agent memory context","search_mode":"vector","n_results":3}'

# 5. 仅关键词检索
curl -X POST http://localhost:5000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"HNSW index optimization","search_mode":"keyword","n_results":3}'

# 6. 带过滤的检索
curl -X POST http://localhost:5000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"database","search_mode":"hybrid","filters":{"year_min":2025,"tag":"AI"}}'

# 7. 查看统计
curl http://localhost:5000/api/stats
```

### 预期

每个 API 调用返回 JSON 结果，其中 `seekdb_mode` 字段表明实际使用的检索模式。

---

## 技术验证总结

| 验证项 | seekdb 功能 | 验证方式 |
|--------|------------|---------|
| 数据写入 | Collection.upsert() | 导入论文后检查 /api/health |
| 向量检索 | HNSW/IVF 索引 | 语义搜索返回相关结果 |
| 全文检索 | MATCH() AGAINST() | 关键词搜索精确匹配 |
| 混合检索 | 单条 SQL 融合 | hybrid 模式 score 综合两种信号 |
| 结构化过滤 | WHERE 子句 | 年份/标签/作者过滤 |
| 元数据管理 | metadata 字段 | 阅读状态追踪 |
