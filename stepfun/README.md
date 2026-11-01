# seekdb × 阶跃星辰 · 端侧混合检索知识库

赛题：**端侧 AI 推理性能优化与 seekdb 混合检索**（20 分）。
代码基于 `powercontext` 仓库 `2026-competition-ecosystem` 分支，全部项目资产位于 `stepfun/`。

这是一个可在 Chrome / Edge 直接使用的迷你知识库：文档在**浏览器内**完成切块与向量化，向量、原文和元数据写入**本机嵌入式 seekdb**；检索时查询向量同样在浏览器内生成，全文召回与 HNSW 向量召回**由 seekdb 在库内融合排序**，前端只负责展示。

## 功能

- 导入：内置 60 篇示例语料；支持上传 `.txt / .md / .json / .csv`、粘贴文本；按 520 字符切块、80 字符重叠，确定性文档 ID 支持重复导入 `upsert`。
- 端侧推理：Transformers.js + ONNX Runtime Web，在 Web Worker 中运行 `bge-small-zh-v1.5`（512 维）；默认 WebGPU + FP16，自动回退 WASM + INT8，界面明确显示实际后端、精度、模型加载耗时与 GPU 适配器。
- seekdb：嵌入式启动，集合内保存向量、原文、元数据；HNSW（cosine）向量索引 + `ngram2` 全文索引；混合检索由 `DBMS_HYBRID_SEARCH` 与 RRF 在库内完成，**没有客户端结果合并或内存检索**。
- 状态管理：新建 / 切换 / 删除集合；导入后调用 `refresh_index()` 让新文档立即可检索；刷新策略与批大小可调；当前集合与偏好持久化。
- 评测：固定语料与 24 条查询，应用内可直接跑 Recall@K / nDCG@K / MRR@K、查询延迟基准与导入基准，并导出原始 JSON。
- 合规：不调用任何云端推理 API；模型与 ORT 运行时全部本地托管；示例与配置仅含占位值，不含真实 API Key、密码或其他凭据。

## 架构

```
浏览器（Chrome / Edge）
  React UI ── Web Worker ── Transformers.js 3.8.1 ── ONNX Runtime Web
                                └─ bge-small-zh-v1.5：WebGPU FP16 / WASM INT8
      │
      │ HTTP/JSON（仅 127.0.0.1）
      ▼
Node.js + Express 5（本地服务，同时托管前端与模型文件）
      └─ seekdb-js 1.4.0（嵌入式原生绑定）
           └─ 本地数据目录 seekdb_data/
                ├─ HNSW 向量索引（512 维，cosine）
                ├─ FULLTEXT 索引（ngram2）
                └─ 元数据 JSON（category / source / lang / title ...）
```

导入链路：文件解析 → 切块 → Worker 批量嵌入 → `POST /api/collections/:name/documents` → seekdb `add/upsert` → `refresh_index()`。

检索链路：问题 → Worker 生成查询向量 → `POST /api/collections/:name/search` → seekdb `hybridSearch`（全文 + KNN，RRF）→ 返回排名、原文与元数据。

## 环境要求

| 项目 | 要求 |
| --- | --- |
| 浏览器 | Chrome / Edge 最新版；WebGPU 需 113+。无 WebGPU 时自动回退 WASM，功能不受影响 |
| 操作系统 | Windows x64 / macOS / Linux x64（取决于 `seekdb@1.4.0` 原生绑定）；实测 Windows 11 x64 |
| Node.js | ≥ 20（实测 v24.15.0） |
| 内存 | 建议 ≥ 4 GB；WASM 回退路径同样可用 |
| 网络 | 运行期无需外网；模型与 ORT 均由本地服务提供 |

## 快速开始

```bash
cd stepfun
npm install                 # 安装依赖；postinstall 会把 ORT 运行时复制到 public/ort
npm run fetch:models        # 下载/校验模型（仓库已含 FP16/INT8 时可跳过）
npm run dev                 # http://127.0.0.1:5173
```

生产构建：

```bash
npm run build
npm start                   # 读取 dist/ 并在同一端口启动 API
```

可用环境变量（均为本地路径 / 端口，无凭据）：

```bash
PORT=5173
SEEKDB_PATH=./seekdb_data
MODEL_BASE_URL=https://hf-mirror.com   # 仅 fetch:models 使用
```

首次打开后模型会自动加载；点击「导入示例语料（60 篇）」即可检索。默认集合 `kb_default` 不可删除。

## 模型与量化

| 项目 | 值 |
| --- | --- |
| 模型 | `Xenova/bge-small-zh-v1.5`（`BAAI/bge-small-zh-v1.5` 的 ONNX 导出，中文，512 维） |
| 版本 | 固定 revision `75c43b069aac4d136ba6bc1122f995fedcfd2781` |
| 来源 | https://huggingface.co/Xenova/bge-small-zh-v1.5/tree/75c43b069aac4d136ba6bc1122f995fedcfd2781 |
| 查询前缀 | `为这个句子生成表示以用于检索相关文章：`（BGE 中文检索建议用法） |
| 池化 / 归一化 | mean pooling + L2 normalize |
| 运行时 | Transformers.js 3.8.1 + ONNX Runtime Web（WebGPU / WASM），Worker 内执行 |

模型文件由 `scripts/fetch-models.mjs` 按 revision 下载，并按字节数与 SHA-256 记录在 `public/models/Xenova/bge-small-zh-v1.5/manifest.json`：

| 精度 | 文件 | 体积（字节 / MiB） | 相对 FP32 压缩比 |
| --- | --- | --- | --- |
| FP32（质量基线） | `onnx/model.onnx` | 94,851,877 / 90.46 | 1.00× |
| FP16（WebGPU 默认） | `onnx/model_fp16.onnx` | 47,497,427 / 45.30 | 2.00× |
| INT8（WASM 默认） | `onnx/model_int8.onnx` | 23,903,394 / 22.80 | 3.97× |

FP16 为权重半精度导出；INT8 为官方导出张量上的训练后动态量化（`quantize_config.json`：`per_channel=true`、`reduce_range=true`、`weight_type=QInt8`）。两种量化都不改变 512 维输出维度。`npm run fetch:models --all` 可同时获取 FP32 基线。

### 检索质量（离线固定集）

方法：同一份 60 篇语料、24 条带分级标注（2/1）的查询；对每个精度分别嵌入，按余弦相似度对全库排序，计算 Recall@5 / Recall@10 / nDCG@10（gain = 2^g − 1）/ MRR@10。运行于 Node CPU（onnxruntime-node），用于对比精度损失，不等同于浏览器耗时。

| 精度 | Recall@5 | Recall@10 | nDCG@10 | MRR@10 | 与 FP32 向量余弦一致度 |
| --- | --- | --- | --- | --- | --- |
| FP32 | 68.75% | 75.00% | 75.56% | 89.58% | 1.0000 |
| FP16 | 68.75% | 75.00% | 75.56% | 89.58% | 1.0000 |
| INT8 | 65.97% | 77.08% | 75.50% | 87.27% | 0.9581 |

INT8 相对 FP32：Recall@5 −2.78pp、Recall@10 +2.08pp、nDCG@10 −0.06pp、MRR@10 −2.31pp。24 条查询规模下属于可接受波动，排序质量基本保持。

## seekdb 集成

- 启动：`new SeekdbClient({ path: SEEKDB_PATH, database: 'test' })`，数据库随 Node 进程启动，无需单独服务。
- 每个集合对应一张表，保存 `id / document / embedding / metadata(JSON)`；建表时声明：
  - `HNSW` 向量索引：`dimension=512`、`distance=cosine`、`embeddingFunction=null`（向量由浏览器提供）；
  - `FULLTEXT` 全文索引：`ngram2` 分词，适合中文短文本。
- 混合检索：`collection.hybridSearch({ query: { whereDocument: { $contains }, where }, knn: { queryEmbeddings, where }, rank: { rrf }, nResults })`，由 seekdb 生成 `DBMS_HYBRID_SEARCH.GET_SQL` 并在库内执行 RRF 融合；元数据过滤同时下推到全文分支和 KNN 分支，前端不做二次排序或过滤。
- 索引刷新：写入后 `refresh_index()`（内部 `CALL dbms_index_manager.refresh()`）；默认整次导入结束刷新一次，也可选择每批刷新做对照。新文档刷新后立即可检索。
- 增量与状态：切块 ID 为 `source|title|passage` 的 FNV-1a 哈希（多块追加 `-cN`），重复导入使用 `upsert` 更新而不产生重复行；集合切换后导入和检索都作用于当前集合；当前集合名保存在 `localStorage`，向量与原文只存在 seekdb 数据目录。
- 默认端口仅绑定 `127.0.0.1`，不对外网开放。

## 使用说明

1. 打开页面，等待「模型与运行后端」显示 `WebGPU · FP16`（或 `WASM · INT8`）。
2. 「导入语料」中导入 60 篇示例，或上传文件 / 粘贴文本；可设置 `metadata category/source`、嵌入批大小与刷新策略。
3. 「混合检索」输入问题，可选 `Top K`、元数据过滤、全文关键词和 RRF 参数；结果卡片显示排名、RRF 距离、原文高亮、category/source/lang 与分阶段耗时。
4. 「量化与检索质量」展示固定评测集的精度对比；「性能基准」可运行 24 条查询的重复测量与 30 篇导入策略对比，并导出原始 JSON。
5. 切换后端 / 精度会重新加载模型；`强制 WASM（回退验证）`用于验证无 WebGPU 路径。

## 性能数据

固定条件：60 篇文档、24 条查询、`k=10`、seekdb 1.4.0 嵌入式、集合已刷新；记录预热后的中位数与 p95，WebGPU 重复 5 轮、WASM 重复 3 轮。

**查询基准（浏览器端到端）**

| 后端 / 精度 | 模式 | 查询向量化（中位） | seekdb 检索（中位） | 端到端（中位 / p95） | 首条 |
| --- | --- | --- | --- | --- | --- |
| WebGPU / FP16 | 混合 | 10.4 ms | 7.22 ms | 21.5 / 25.8 ms | 22.6 ms |
| WebGPU / FP16 | 纯向量 | 9.8 ms | 1.55 ms | 15.5 / 21.6 ms | 16.6 ms |
| WASM / INT8 | 混合 | 22.5 ms | 9.75 ms | 36.05 / 43.9 ms | 43.3 ms |
| WASM / INT8 | 纯向量 | 22.25 ms | 1.78 ms | 28.15 / 34.8 ms | 28.3 ms |

WebGPU 混合检索在预热前的会话首查为 82.2 ms（含 GPU 管线首次执行开销）；表中「首条」指预热之后、正式重复测量前的首条记录。模型加载本身在 Worker 内完成，本次实测 WebGPU FP16 冷加载 791.8 ms（界面显示值）。

**导入基准（30 篇文档 upsert 到已有 60 篇的集合，WebGPU FP16）**

| 策略 | 向量化 | 写入 | 刷新索引 | 总计 |
| --- | --- | --- | --- | --- |
| batch=1 + 每批刷新（基线） | 468 ms | 320 ms | 11,090 ms | 12,351 ms |
| batch=8 + 结束时刷新 | 112 ms | 324 ms | 302 ms | **844 ms** |
| batch=32 + 结束时刷新 | 88 ms | 311 ms | 403 ms | 860 ms |
| batch=32 + 每批刷新（对照） | 118 ms | 305 ms | 404 ms | 897 ms |

推荐策略相对基线约 **14.6×** 加速；主要收益来自把逐批索引刷新合并为一次，其次来自批量嵌入。更多原始样本见 `data/results/`。

## 复现与数据

```bash
npm run typecheck             # TypeScript 检查
npm run fetch:models --all    # 离线质量评测需要 FP32 基线（FP16/INT8 仓库已含）
npm run eval:quality          # 生成 public/data/quality.json 与 data/results/quality-*.json
npm run dev                   # 应用内运行查询 / 导入基准，可导出原始 JSON
```

已提交的原始数据（2026-11-01）：

- `data/results/benchmark-webgpu-query-24q-2026-11-01.json`：WebGPU FP16，24 查询 × 5 轮，全部逐条样本；
- `data/results/benchmark-wasm-query-24q-2026-11-01.json`：WASM INT8，24 查询 × 3 轮；
- `data/results/benchmark-webgpu-import-30docs-2026-11-01.json`：导入策略对比逐批样本；
- `data/results/quality-2026-11-01T08-49-18-770Z.json`：FP32 / FP16 / INT8 离线质量评估。

评测环境：Windows 11 x64（10.0.26200），24 逻辑核；Chromium 150（Qoder 内置浏览器，Electron 43.1.1）WebGPU 可用，GPU 适配器 `nvidia · blackwell`；WASM 路径为同一浏览器强制选择。页面不依赖 Qoder 专有接口，Chrome / Edge 最新版可直接运行；未单独在 Edge 上复测。

## 目录结构

```
stepfun/
├─ server/                  # Express API、嵌入式 seekdb 存储、配置、安全日志
├─ src/                     # React 19 前端、Worker、检索/质量/基准逻辑
├─ public/
│  ├─ data/                 # 示例语料、评测集、质量报告
│  └─ models/               # 本地 ONNX 模型（FP16/INT8 已随仓库提供）
├─ scripts/                 # 模型下载、ORT 复制、离线质量评测
├─ data/results/            # 原始基准与质量数据（可复核）
├─ index.html
└─ package.json
```

## 合规与安全

- 向量化 100% 在浏览器 Web Worker 内完成（Transformers.js / ORT Web），没有云端推理调用，也没有伪装成端侧的远程推理。
- 检索 100% 由 seekdb 执行，前端不缓存全量向量、不做内存相似度搜索、不合并两路结果；示例与评测结果均为现场计算，不播放预录结果。
- 模型与 ORT wasm 从本机静态目录加载（`env.allowRemoteModels=false`），不依赖 CDN。
- 配置示例使用占位值，不提交真实 API Key、密码或其他凭据；服务默认只监听 `127.0.0.1`。
- `seekdb_*/` 运行时数据目录、`dist/`、`node_modules/`、`.env*` 已加入 `.gitignore`。

## 已知限制

- 内置语料为 60 篇技术文档、24 条查询，规模用于可复现对比，不代表大规模生产负载。
- WebGPU 延迟与 GPU 型号强相关；本次仅记录一种设备。WASM 路径为单线程（`numThreads=1`，避免 COOP/COEP 要求）。
- 元数据过滤界面只暴露 `category` 等值过滤；服务端 `where` 支持 seekdb 的等值 / `$in` / 范围等操作符。
- 导入基准主要覆盖 30 篇规模，更大批量的索引刷新成本需按数据量重新测量。
