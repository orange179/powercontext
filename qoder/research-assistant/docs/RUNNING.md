# 运行说明（文献整理助手）

## 环境要求

- Python 3.11 及以上（在 Python 3.12 / Windows 11 上实测通过）
- 无需 Docker、外部数据库、模型 API Key
- 依赖中包含 PowerContext 1.2.0；其 Server 以进程内 ASGI 方式启动，数据存放在本地 SQLite

## 1. 获取代码

项目位于竞赛生态分支 `qoder-competition`（基于 `2026-competition-ecosystem`）的 `qoder/research-assistant` 目录：

```bash
git clone -b qoder-competition https://github.com/orange179/powercontext.git
cd powercontext/qoder/research-assistant
```

## 2. 安装依赖

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
```

`requirements.txt` 只有一项：`powercontext[server]==1.2.0`，它会带入 FastAPI、uvicorn、httpx、aiosqlite 等运行依赖。

## 3. 启动服务

```bash
python backend/main.py
```

首次启动时 PowerContext 需要初始化本地数据库，可能需要 10–30 秒。

- 应用页面：<http://127.0.0.1:8000>
- OpenAPI 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>（返回 `"tech": "PowerContext"` 与 `search_modes`）

也可以使用脚本（Linux / macOS）：

```bash
./start.sh
```

## 4. 功能演示

### 4.1 导入文献

1. 打开 <http://127.0.0.1:8000>
2. 点击“导入文献”标签
3. 点击“填入示例数据”（读取内置 `data/sample_papers.csv`），再点击“导入”

预期结果：提示“成功导入 7 篇文献”，统计变为 7 篇文献 / 15 个标签。
每篇文献都已通过 `remember_memory(kind="paper")` 写入 PowerContext 的“文献库” Scope。

### 4.2 全文检索

1. 点击“检索文献”标签
2. 输入 `NLP`，点击“检索”

预期结果：返回 3 篇文献（Attention Is All You Need、BERT、GPT-3），并显示相对匹配度。
结果是 `search_memory(mode="fts")` 的真实命中，不是前端过滤。

### 4.3 偏好记忆与推荐

1. 点击“个人偏好”标签，用户 ID 保持 `user1`
2. 选择 `NLP`、`Transformer`，点击“保存偏好”
3. 点击“查看推荐”

预期结果：偏好写入该用户独立的 PowerContext Scope；推荐接口先召回偏好 Memory，再按标签检索文献库，返回 3 条带“命中标签”的推荐。

### 4.4 文献列表

点击“文献列表”标签，可查看已导入的全部文献。

## 5. 一键验证（推荐给审核）

```bash
python scripts/test_backend.py
```

脚本会启动真实的应用（含进程内 PowerContext），依次执行：导入 7 篇 → 检索 NLP → 保存偏好 → 召回偏好 → 生成推荐 → 健康检查。

实测输出：

```text
[startup] PowerContext ready, search_modes=[auto, fts]
[import] 200 imported= 7
[documents] 200 count= 7
[search] 200 hits= 3
   - Attention Is All You Need ...
   - BERT: Pre-training of Deep Bidirectional Transformers ...
   - GPT-3: Language Models are Few-Shot Learners ...
[save prefs] 200 {'status': 'ok', ...}
[recall prefs] 200 {'preferred_tags': ['NLP', 'Transformer'], ...}
[recommendations] 200 ['Attention Is All You Need', 'BERT: ...', 'GPT-3: ...']
[health] 200 {'status': 'ok', 'tech': 'PowerContext', 'search_modes': ['auto', 'fts'], ...}
[DONE] backend + PowerContext end-to-end OK
```

另有最小验证脚本，只验证“写入记忆 → 召回记忆”：

```bash
python scripts/verify_powercontext.py
```

## 6. API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/documents/import` | 提交 CSV 文本，逐篇 `remember_memory` 写入文献库 Scope |
| GET | `/api/documents` | 文献列表 |
| POST | `/api/search` | JSON `{"query": "...", "top_k": 10}`，调用 `search_memory(mode="fts")` |
| GET | `/api/user/{user_id}/preferences` | 从用户 Scope 召回偏好 Memory |
| POST | `/api/user/{user_id}/preferences` | 保存偏好 Memory（`kind="preference"`） |
| GET | `/api/user/{user_id}/recommendations` | 偏好召回 → 标签 → 文献检索 |
| GET | `/health` | 服务与 PowerContext 能力状态 |

## 7. 数据与重置

- PowerContext 数据：`backend/.powercontext-data/powercontext.db`（SQLite）
- 想从空库演示：停止服务后删除 `backend/.powercontext-data` 目录，再启动

## 8. 故障排查

### 端口被占用

```bash
# Windows 查看占用 8000 端口的进程
netstat -ano | findstr :8000
```

或修改 `backend/main.py` 末尾的 `uvicorn.run(..., port=8000)`。

### 启动较慢 / 看似卡住

PowerContext 首次启动需要建库，等待 10–30 秒后访问 `/health` 确认。

### `No module named 'powercontext'`

确认已激活虚拟环境并执行 `pip install -r requirements.txt`，且 Python 版本 ≥ 3.11。

### 依赖下载慢（中国大陆网络）

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Windows 终端中文显示乱码

只影响控制台打印，不影响页面与接口数据。

## 9. 关于技术选型

赛题要求 seekdb 与 PowerContext 至少使用一种。本项目实际使用 **PowerContext 1.2.0** 完成文献存储、全文检索与用户记忆，
未使用 seekdb（`pylibseekdb` 仅支持 Linux/macOS，且当前功能不需要它）。因此项目依赖只有 PowerContext，不存在依赖冲突。
