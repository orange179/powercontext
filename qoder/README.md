# ResearchFlow - 科研文献智能检索助手

基于 seekdb 混合检索能力的科研文献管理工具，帮助研究者快速定位相关文献段落。

## 项目简介

科研工作者日常需要管理大量文献，传统关键词搜索难以理解语义，纯向量搜索又无法精确匹配专业术语。ResearchFlow 基于 seekdb 的混合检索能力，将**向量语义搜索**、**全文关键词搜索**和**结构化条件过滤**统一在一条查询中。

## 核心功能

- **混合检索**：一条查询同时执行向量相似度搜索 + BM25 全文匹配 + 结构化过滤（年份、标签、作者）
- **文献管理**：导入、浏览、编辑、删除文献记录，支持阅读状态追踪
- **语义理解**：支持自然语言查询，理解搜索意图而非仅匹配关键词
- **数据看板**：可视化展示文献库统计信息

## 技术架构

| 组件 | 技术 | 说明 |
|------|------|------|
| 搜索引擎 | seekdb (pyseekdb) | 向量索引 + 全文索引 + 关系存储 |
| 后端 | Python Flask | REST API 服务 |
| 前端 | HTML/CSS/JavaScript | 单页应用 |
| 部署模式 | 嵌入式 / 远程服务器 / 模拟 | 跨平台兼容 |

### seekdb 在项目中的作用

seekdb 是本项目的核心检索引擎，提供以下能力：

1. **向量存储与检索**：论文内容自动嵌入为向量，支持语义相似度搜索
2. **全文索引**：使用 IK 分析器支持中英文全文检索
3. **混合查询**：一条 SQL 同时执行向量搜索 + 全文匹配 + 结构化过滤
4. **嵌入式部署**：单个 `.db` 文件即可运行，无需额外服务

示例查询 SQL：
```sql
SELECT id, title,
    l2_distance(embedding, '<query_vector>') AS vec_score,
    MATCH(title, abstract, content) AGAINST('关键词') AS text_score
FROM research_papers
WHERE MATCH(title, abstract, content) AGAINST('vector search')
    AND year >= 2024
    AND tags LIKE '%database%'
ORDER BY (0.6 * vec_score + 0.4 * text_score) DESC
LIMIT 10;
```

## 运行环境

- Python 3.11+
- pip

## 安装步骤

### 1. 克隆项目

```bash
git clone https://github.com/oceanbase/powercontext.git
cd powercontext/qoder
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

依赖列表：
- `flask>=3.0` - Web 框架
- `flask-cors>=4.0` - 跨域支持
- `pyseekdb>=1.4.0` - seekdb Python SDK
- `pymysql>=1.1` - MySQL 协议驱动

### 3. 配置（可选）

复制环境变量模板：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```ini
# seekdb 连接模式
# auto      - 自动检测（Linux 用嵌入式，Windows 用远程或模拟）
# embedded  - 嵌入式模式（仅 Linux，需要 pylibseekdb）
# remote    - 远程服务器模式（连接 seekdb Docker/Cloud 实例）
# simulated - 模拟模式（无需 seekdb，用于演示）
SEEKDB_MODE=auto

# 远程模式配置（仅 SEEKDB_MODE=remote 时需要）
SEEKDB_HOST=localhost
SEEKDB_PORT=2881
```

### 4. 启动 seekdb（远程模式）

如果使用远程模式，需要先启动 seekdb 服务器：

**方式 A：Docker**
```bash
docker run -d --name seekdb -p 2881:2881 -p 2886:2886 \
    -v ./data:/var/lib/oceanbase \
    oceanbase/seekdb:latest
```

**方式 B：Cloud D0 实例**
```bash
curl -X POST https://d0.seekdb.ai/api/v1/instances
```

### 5. 启动应用

```bash
cd backend
python app.py
```

启动成功后会显示：
```
  ResearchFlow - 科研文献智能检索助手
  seekdb mode: embedded / remote / simulated
  Running at http://localhost:5000
```

### 6. 访问

打开浏览器访问 http://localhost:5000

## 使用说明

### 导入示例数据

1. 进入「文献管理」标签页
2. 点击「导入示例数据」按钮
3. 系统将导入 10 篇示例论文

### 混合检索

1. 在「智能检索」标签页输入查询
2. 选择检索模式：
   - **混合检索**（推荐）：同时使用向量语义 + 关键词匹配
   - **语义向量检索**：仅使用向量相似度
   - **关键词全文检索**：仅使用 BM25 全文匹配
3. 可选：添加过滤条件（标签、年份范围）
4. 点击「检索」按钮

### 文献管理

- **添加文献**：点击「添加文献」按钮，填写标题、摘要、作者等信息
- **修改状态**：点击文献右侧的循环按钮切换阅读状态（未读 → 在读 → 已读）
- **删除文献**：点击文献右侧的删除按钮

### 数据看板

查看文献库统计信息：
- 文献总数
- seekdb 运行模式
- 阅读状态分布
- 标签分布
- 年份分布

## 验证样例

详见 [docs/verification.md](docs/verification.md)

## 项目结构

```
qoder/
├── README.md                    # 本文件
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量模板
├── backend/
│   ├── app.py                   # Flask 应用主入口
│   ├── seekdb_service.py        # seekdb 集成层
│   └── config.py                # 配置文件
├── frontend/
│   ├── index.html               # 前端页面
│   ├── css/style.css            # 样式
│   └── js/app.js                # 前端逻辑
├── data/
│   └── sample_papers.json       # 示例论文数据
└── docs/
    ├── verification.md          # 验证样例
    └── dev_log.md               # Qoder 开发记录
```

## API 文档

### Health Check
```
GET /api/health
Response: {"status": "ok", "seekdb_available": true, "seekdb_mode": "embedded"}
```

### Import Sample Data
```
POST /api/import-sample
Response: {"imported": 10, "ids": [...]}
```

### List Papers
```
GET /api/papers?reading_status=read&year_min=2025
Response: {"papers": [...], "total": 5}
```

### Add Paper
```
POST /api/papers
Body: {
    "title": "Paper Title",
    "abstract": "...",
    "content": "...",
    "authors": ["Author1", "Author2"],
    "year": 2026,
    "tags": ["tag1", "tag2"]
}
```

### Search
```
POST /api/search
Body: {
    "query": "vector search",
    "search_mode": "hybrid",
    "n_results": 10,
    "filters": {"year_min": 2024, "tag": "database"}
}
Response: {"query": "...", "search_mode": "hybrid", "results": [...], "total": 5}
```

### Statistics
```
GET /api/stats
Response: {
    "total_papers": 10,
    "seekdb_mode": "embedded",
    "tags": {...},
    "reading_status": {...},
    "papers_by_year": {...}
}
```

## 在线演示

**项目网站**：https://researchflow-a9ws7ze9c40.qoder.zone

## 相关链接

- [seekdb GitHub](https://github.com/oceanbase/seekdb)
- [seekdb 文档](https://github.com/oceanbase/seekdb-doc)
- [PowerContext GitHub](https://github.com/oceanbase/powercontext)
- [pyseekdb PyPI](https://pypi.org/project/pyseekdb/)
- [Qoder Sites 项目网站](https://researchflow-a9ws7ze9c40.qoder.zone)

## License

Apache-2.0
