# 一页技术说明：端侧 AI 推理性能优化与 seekdb 混合检索

## 目标与架构

做一个零后端依赖的迷你知识库：文档导入、切块、向量化全部在浏览器完成；向量、原文和元数据写入本机嵌入式 seekdb；查询在浏览器内编码后，由 seekdb 同时执行全文与 HNSW 召回，并在库内用 RRF 融合。Node/Express 只作为本地静态服务与跨进程 API，不参与推理，也不合并检索结果。

```
React UI → Web Worker（Transformers.js 3.8.1 + ORT Web）→ 本地 Express API → seekdb-js 1.4.0（嵌入式）
                                     ↑ 查询向量                       ↓ DBMS_HYBRID_SEARCH + RRF
```

## 端侧模型与量化

模型固定为 `Xenova/bge-small-zh-v1.5`（revision `75c43b069aac4d136ba6bc1122f995fedcfd2781`），512 维中文嵌入，mean pooling + L2 归一化，查询加 BGE 中文检索前缀。模型与 ORT wasm 由本地服务提供，`allowRemoteModels=false`，运行期不访问云端。

| 精度 | ONNX 体积 | 压缩比 | Recall@5 | Recall@10 | nDCG@10 | MRR@10 | 向量一致度 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FP32 | 90.46 MiB | 1.00× | 68.75% | 75.00% | 75.56% | 89.58% | 1.0000 |
| FP16 | 45.30 MiB | 2.00× | 68.75% | 75.00% | 75.56% | 89.58% | 1.0000 |
| INT8 | 22.80 MiB | 3.97× | 65.97% | 77.08% | 75.50% | 87.27% | 0.9581 |

FP16 为权重半精度导出；INT8 为官方导出上的训练后动态量化（per-channel、reduce_range、QInt8），不改变向量维度。质量口径：60 篇固定语料、24 条分级查询，全库余弦排序；INT8 相对 FP32 的 nDCG@10 仅差 0.06pp，排序质量基本保持。

## seekdb 集成

每个集合一张表，列包含 `id`、原文、512 维向量和 JSON 元数据；建表声明 HNSW（dimension=512、cosine）和 FULLTEXT（ngram2）索引。检索调用：

```js
collection.hybridSearch({
  query: { whereDocument: { $contains: keyword }, where },
  knn:   { queryEmbeddings, where },
  rank:  { rrf: { rankWindowSize, rankConstant } },
  nResults,
});
```

全文与向量两路召回、RRF 融合、元数据过滤全部在 seekdb 内完成；过滤条件同时下推到两路，避免未过滤的 KNN 结果混入。写入后调用 `refresh_index()`（`CALL dbms_index_manager.refresh()`）使新文档立即可检索。导入使用确定性 ID（source|title|passage 的 FNV-1a，多块加 `-cN`）与 `upsert`，增量导入不产生重复行；集合支持新建、切换、删除，当前集合名持久化在 `localStorage`，向量与原文只落在 seekdb 数据目录。

## 优化与实测

设备：Windows 11 x64、24 逻辑核、Chromium 150，WebGPU 适配器 `nvidia · blackwell`；60 篇文档、24 条查询、k=10。

| 后端 / 精度 | 混合检索端到端（中位 / p95） | 纯向量端到端（中位） | 冷启动首查 |
| --- | --- | --- | --- |
| WebGPU / FP16 | 21.5 / 25.8 ms | 15.5 ms | 82.2 ms |
| WASM / INT8 | 36.05 / 43.9 ms | 28.15 ms | 44.8 ms |

其中 WebGPU 混合检索的查询向量化 10.4 ms、seekdb 检索 7.22 ms；WASM 分别为 22.5 ms 与 9.75 ms。优化手段：Worker 内只加载一次模型并复用会话；WebGPU FP16 与 WASM INT8 自动选择/手动强制，界面显示实际后端、精度、加载耗时与适配器；嵌入按 batch 8 组织；导入只在结束时刷新索引。

| 30 篇导入策略 | 向量化 | 刷新索引 | 总计 |
| --- | --- | --- | --- |
| 逐条嵌入 + 每批刷新（基线） | 468 ms | 11,090 ms | 12,351 ms |
| batch 8 + 结束时刷新 | 112 ms | 302 ms | **844 ms** |

相对基线约 14.6×；收益主要来自把 30 次索引刷新合并为 1 次。模型加载实测 791.8 ms（WebGPU FP16，冷加载）。所有耗时按阶段记录，查询基准先预热，取 5 轮（WASM 3 轮）中位数与 p95；原始逐条样本在 `data/results/`。

## 兼容性与复现

WebGPU 存在时默认 FP16；不存在或初始化失败时自动回退 WASM INT8，`强制 WASM` 可验证回退路径，UI 始终标注实际后端。WASM 使用单线程，避免 COOP/COEP 配置。`npm run eval:quality` 重建质量报告，应用内可重跑查询/导入基准并导出 JSON；`npm run typecheck`、`npm run build` 已通过。模型 revision、SHA-256、语料、qrels、seekdb 参数均随仓库固定。

## 结论与限制

在完全端侧、无云端推理的前提下，混合检索热查询达到约 21.5 ms（本机 WebGPU），INT8 量化把模型压到 22.8 MiB 且排序质量基本无损，索引刷新合并使导入提速 14.6×。当前评测为单设备、60 篇级语料；更大数据量、其他 GPU / 浏览器仍需追加测量。配置示例均为占位值，不包含任何真实凭据。
