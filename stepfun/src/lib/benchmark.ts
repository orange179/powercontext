import {
  addDocuments,
  collectionStats,
  createCollection,
  deleteCollection,
  refreshIndex,
  searchDocuments,
} from './api';
import type {
  ImportBenchRun,
  ImportBenchmarkResult,
  LatencyStats,
  QueryBenchSample,
  QueryBenchmarkResult,
} from './app-types';
import type { EmbeddingClient } from './embedding';
import { averageMetrics, rankingMetrics } from './metrics';
import { QUERY_PREFIX } from './model';
import { toDocumentRecord } from './records';
import { mean, median, percentile, round } from './stats';
import type { EvalSet, PreparedDoc, SearchMode } from './types';

const now = () => performance.now();

function summarize(values: number[]): LatencyStats {
  if (values.length === 0) {
    return { firstMs: null, medianMs: 0, meanMs: 0, p95Ms: 0, minMs: 0, maxMs: 0, count: 0 };
  }
  return {
    firstMs: round(values[0], 2),
    medianMs: round(median(values), 2),
    meanMs: round(mean(values), 2),
    p95Ms: round(percentile(values, 95), 2),
    minMs: round(Math.min(...values), 2),
    maxMs: round(Math.max(...values), 2),
    count: values.length,
  };
}

interface TimedQuery {
  embedMs: number;
  searchMs: number;
  totalMs: number;
  topIds: string[];
}

async function timedQuery(
  client: EmbeddingClient,
  collection: string,
  mode: SearchMode,
  query: string,
  k: number,
): Promise<TimedQuery> {
  const started = now();
  const embedStart = now();
  const embedded = await client.embed([query], { batchSize: 1, prefix: QUERY_PREFIX });
  const embedMs = now() - embedStart;

  const response = await searchDocuments(collection, {
    query,
    embedding: embedded.vectors[0],
    k,
    mode,
    keyword: query,
  });

  return {
    embedMs: round(embedMs, 2),
    searchMs: response.timings.searchMs,
    totalMs: round(now() - started, 2),
    topIds: response.results.map((hit) => hit.id),
  };
}

export async function runQueryBenchmark(options: {
  client: EmbeddingClient;
  collection: string;
  collectionCount: number;
  corpusCount: number;
  evalSet: EvalSet;
  modes: SearchMode[];
  repetitions: number;
  k: number;
  backend: string;
  dtype: string;
  onProgress?: (progress: { done: number; total: number; label: string }) => void;
}): Promise<QueryBenchmarkResult> {
  const { client, collection, evalSet, modes, repetitions, k } = options;
  const queries = evalSet.queries;
  const total = 1 + modes.length * queries.length * repetitions;
  let done = 0;
  const report = (label: string) => {
    options.onProgress?.({ done, total, label });
  };

  report('预热查询（冷路径）');
  const warmup = await timedQuery(client, collection, modes[0] ?? 'hybrid', queries[0].query, k);
  done += 1;
  report('预热完成');

  const modeResults: QueryBenchmarkResult['modes'] = [];
  for (const mode of modes) {
    const samples: QueryBenchSample[] = [];
    for (const item of queries) {
      for (let rep = 1; rep <= repetitions; rep += 1) {
        const timed = await timedQuery(client, collection, mode, item.query, k);
        samples.push({
          mode,
          queryId: item.id,
          query: item.query,
          rep,
          embedMs: timed.embedMs,
          searchMs: timed.searchMs,
          totalMs: timed.totalMs,
          topIds: timed.topIds,
        });
        done += 1;
        report(`${mode === 'hybrid' ? '混合检索' : '纯向量'} ${item.id} 第 ${rep} 轮`);
      }
    }

    const finalSamples = samples.filter((sample) => sample.rep === repetitions);
    const metricSets = finalSamples.map((sample) => {
      const query = queries.find((item) => item.id === sample.queryId);
      return rankingMetrics(sample.topIds, query?.relevant ?? []);
    });

    modeResults.push({
      mode,
      embed: summarize(samples.map((sample) => sample.embedMs)),
      search: summarize(samples.map((sample) => sample.searchMs)),
      endToEnd: summarize(samples.map((sample) => sample.totalMs)),
      metrics: averageMetrics(metricSets),
      samples,
    });
  }

  return {
    generatedAt: new Date().toISOString(),
    backend: options.backend,
    dtype: options.dtype,
    collection,
    collectionCount: options.collectionCount,
    corpusCount: options.corpusCount,
    k,
    repetitions,
    queryCount: queries.length,
    warmup,
    modes: modeResults,
    note: '查询集与相关性标注固定；首条预热查询单独记录为冷路径，统计值取预热后的重复测量。检索指标取最后一轮的 seekdb 返回结果计算。',
  };
}

interface ImportBenchConfig {
  label: string;
  batchSize: number;
  refreshEachBatch: boolean;
}

export async function runImportBenchmark(options: {
  client: EmbeddingClient;
  docs: PreparedDoc[];
  configs: ImportBenchConfig[];
  backend: string;
  dtype: string;
  onProgress?: (progress: { done: number; total: number; label: string }) => void;
}): Promise<ImportBenchmarkResult> {
  const { client, docs, configs } = options;
  const totalWork = configs.reduce((sum, config) => sum + Math.ceil(docs.length / config.batchSize), 0);
  let doneWork = 0;
  const stamp = Date.now().toString(36);
  const runs: ImportBenchRun[] = [];

  for (let index = 0; index < configs.length; index += 1) {
    const config = configs[index];
    const name = `bench_${stamp}_${index}`;
    const batchCount = Math.ceil(docs.length / config.batchSize);
    const run: ImportBenchRun = {
      id: name,
      label: config.label,
      batchSize: config.batchSize,
      refreshEachBatch: config.refreshEachBatch,
      docCount: docs.length,
      embedMs: 0,
      writeMs: 0,
      refreshMs: 0,
      totalMs: 0,
      perBatchEmbedMs: [],
      perBatchWriteMs: [],
      perBatchRefreshMs: [],
      batchCount,
      refreshCount: config.refreshEachBatch ? batchCount : 1,
      finalCount: 0,
      status: 'running',
    };
    runs.push(run);

    const started = now();
    try {
      await createCollection(name);

      for (let start = 0; start < docs.length; start += config.batchSize) {
        const batch = docs.slice(start, start + config.batchSize);
        const embedStart = now();
        const embedded = await client.embed(
          batch.map((doc) => doc.text),
          { batchSize: config.batchSize },
        );
        const embedMs = now() - embedStart;
        run.embedMs += embedMs;
        run.perBatchEmbedMs.push(round(embedMs, 2));

        const added = await addDocuments(
          name,
          batch.map((doc, offset) => toDocumentRecord(doc, embedded.vectors[offset])),
          { mode: 'upsert', refresh: config.refreshEachBatch },
        );
        run.writeMs += added.timings.writeMs;
        run.perBatchWriteMs.push(added.timings.writeMs);
        if (config.refreshEachBatch) {
          run.refreshMs += added.timings.refreshMs;
          run.perBatchRefreshMs.push(added.timings.refreshMs);
        }

        doneWork += 1;
        options.onProgress?.({
          done: doneWork,
          total: totalWork,
          label: `${config.label}：第 ${Math.min(start + config.batchSize, docs.length)}/${docs.length} 条`,
        });
      }

      if (!config.refreshEachBatch) {
        const refreshed = await refreshIndex(name);
        run.refreshMs += refreshed.timings.refreshMs;
      }

      const stats = await collectionStats(name);
      run.finalCount = stats.collection.count;
      run.totalMs = round(now() - started, 2);
      run.status = 'done';
    } catch (error) {
      run.status = 'error';
      run.error = error instanceof Error ? error.message : String(error);
      run.totalMs = round(now() - started, 2);
    } finally {
      try {
        await deleteCollection(name);
      } catch (error) {
        run.cleanupError = error instanceof Error ? error.message : String(error);
      }
    }
  }

  return {
    generatedAt: new Date().toISOString(),
    backend: options.backend,
    dtype: options.dtype,
    docCount: docs.length,
    runs,
    note: '每种配置写入独立的临时集合，结束后删除；embedding 为浏览器端实际耗时，write/refresh 为服务端 seekdb 计时。文档、模型与后端保持一致，仅批大小与刷新策略变化。',
  };
}
