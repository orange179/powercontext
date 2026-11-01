#!/usr/bin/env node
/**
 * Offline retrieval-quality evaluation for the embeddings used in the app.
 *
 * For each precision (fp32 baseline, fp16, int8) it embeds the fixed corpus and
 * query set with Transformers.js (ONNX), ranks all documents by cosine similarity
 * and reports Recall@5, Recall@10, nDCG@10, MRR@10 plus vector fidelity vs FP32.
 *
 * Usage:
 *   node scripts/eval-quality.mjs                 # fp32, fp16, int8
 *   node scripts/eval-quality.mjs --dtypes=int8   # subset
 */
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { env, pipeline } from '@huggingface/transformers';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const MODEL_ID = 'Xenova/bge-small-zh-v1.5';
const MODEL_REVISION = '75c43b069aac4d136ba6bc1122f995fedcfd2781';
const QUERY_PREFIX = '为这个句子生成表示以用于检索相关文章：';
const K = 10;

const arg = process.argv.find((a) => a.startsWith('--dtypes='));
const dtypes = arg ? arg.split('=')[1].split(',') : ['fp32', 'fp16', 'int8'];

env.allowRemoteModels = false;
env.localModelPath = path.join(ROOT, 'public', 'models');
env.backends.onnx.wasm.numThreads = 1;

const corpus = JSON.parse(await fsp.readFile(path.join(ROOT, 'public', 'data', 'corpus.json'), 'utf8'));
const evalSet = JSON.parse(await fsp.readFile(path.join(ROOT, 'public', 'data', 'eval.json'), 'utf8'));
const queries = evalSet.queries;

const dot = (a, b) => {
  let sum = 0;
  for (let i = 0; i < a.length; i += 1) sum += a[i] * b[i];
  return sum;
};

const normalize = (v) => {
  let norm = 0;
  for (const x of v) norm += x * x;
  norm = Math.sqrt(norm) || 1;
  return v.map((x) => x / norm);
};

function dcg(gains) {
  return gains.reduce((sum, gain, index) => sum + (Math.pow(2, gain) - 1) / Math.log2(index + 2), 0);
}

function evaluate(rankings, labels) {
  let recall5 = 0;
  let recall10 = 0;
  let ndcg10 = 0;
  let mrr = 0;
  const perQuery = [];
  for (const query of queries) {
    const ranked = rankings.get(query.id);
    const relevant = new Map(query.relevant.map((r) => [r.id, r.grade]));
    const topK = ranked.slice(0, K);
    const hits5 = topK.slice(0, 5).filter((id) => relevant.has(id)).length;
    const hits10 = topK.filter((id) => relevant.has(id)).length;
    const relevantTotal = relevant.size;
    const r5 = relevantTotal ? hits5 / relevantTotal : 0;
    const r10 = relevantTotal ? hits10 / relevantTotal : 0;
    const gains = topK.map((id) => relevant.get(id) ?? 0);
    const idealGains = [...relevant.values()].sort((a, b) => b - a).slice(0, K);
    const d = dcg(gains);
    const idcg = dcg(idealGains);
    const ndcg = idcg > 0 ? d / idcg : 0;
    const firstHit = topK.findIndex((id) => relevant.has(id));
    const rr = firstHit >= 0 ? 1 / (firstHit + 1) : 0;
    recall5 += r5;
    recall10 += r10;
    ndcg10 += ndcg;
    mrr += rr;
    perQuery.push({ id: query.id, query: query.query, recall5: r5, recall10: r10, ndcg10: ndcg, rr, top10: topK });
  }
  const n = queries.length;
  return {
    metrics: {
      'Recall@5': recall5 / n,
      'Recall@10': recall10 / n,
      'nDCG@10': ndcg10 / n,
      'MRR@10': mrr / n,
    },
    perQuery,
    labels,
  };
}

async function embedAll(extractor, texts, batchSize = 16) {
  const vectors = [];
  const batchMs = [];
  const started = performance.now();
  for (let start = 0; start < texts.length; start += batchSize) {
    const batch = texts.slice(start, start + batchSize);
    const t0 = performance.now();
    const output = await extractor(batch, { pooling: 'mean', normalize: true });
    batchMs.push(performance.now() - t0);
    const rows = output.tolist();
    for (const row of rows) vectors.push(normalize(row));
  }
  return { vectors, totalMs: performance.now() - started, batchMs };
}

const modelManifest = JSON.parse(await fsp.readFile(path.join(ROOT, 'public', 'models', MODEL_ID, 'manifest.json'), 'utf8'));
const onnxSizes = Object.fromEntries(
  modelManifest.files
    .filter((f) => f.file.endsWith('.onnx'))
    .map((f) => [path.basename(f.file, '.onnx').replace('model_', '').replace('model', 'fp32'), f.bytes]),
);

const output = {
  generatedAt: new Date().toISOString(),
  model: {
    id: MODEL_ID,
    revision: MODEL_REVISION,
    dimensions: 512,
    queryPrefix: QUERY_PREFIX,
    source: `https://huggingface.co/${MODEL_ID}/tree/${MODEL_REVISION}`,
  },
  config: {
    corpusSize: corpus.length,
    queryCount: queries.length,
    topK: K,
    metrics: 'cosine similarity over all corpus documents; qrels are graded 2/1',
    pooling: 'mean',
    normalize: true,
    wasmThreads: 1,
    runtime: `Node ${process.version} / Transformers.js (onnxruntime-node CPU)`,
  },
  onnxSizesBytes: onnxSizes,
  precisions: {},
};

let baseline = null;
for (const dtype of dtypes) {
  console.log(`\n=== ${dtype} ===`);
  const loadStart = performance.now();
  const extractor = await pipeline('feature-extraction', MODEL_ID, { dtype, device: 'cpu' });
  const loadMs = performance.now() - loadStart;
  const docs = await embedAll(extractor, corpus.map((d) => d.text));
  const queryVectors = await embedAll(extractor, queries.map((q) => `${QUERY_PREFIX}${q.query}`));
  const rankings = new Map();
  for (let qi = 0; qi < queries.length; qi += 1) {
    const scored = corpus.map((doc, di) => ({ id: doc.id, score: dot(queryVectors.vectors[qi], docs.vectors[di]) }));
    scored.sort((a, b) => b.score - a.score);
    rankings.set(queries[qi].id, scored.slice(0, K).map((s) => s.id));
  }
  const evaluation = evaluate(rankings, evalSet);
  let fidelity = null;
  if (baseline) {
    let sum = 0;
    for (let i = 0; i < docs.vectors.length; i += 1) sum += dot(docs.vectors[i], baseline.docs.vectors[i]);
    fidelity = sum / docs.vectors.length;
  }
  output.precisions[dtype] = {
    metrics: evaluation.metrics,
    vectorFidelityVsFp32: fidelity,
    timings: {
      loadMs: Math.round(loadMs),
      documentEmbeddingMs: Math.round(docs.totalMs),
      queryEmbeddingMs: Math.round(queryVectors.totalMs),
      documentEmbeddingMsPerDoc: Math.round((docs.totalMs / corpus.length) * 100) / 100,
    },
    batches: { documentBatchMs: docs.batchMs.map((v) => Math.round(v * 100) / 100), queryBatchMs: queryVectors.batchMs.map((v) => Math.round(v * 100) / 100) },
    perQuery: evaluation.perQuery,
  };
  console.log(`metrics ${JSON.stringify(evaluation.metrics)}`);
  if (fidelity != null) console.log(`vector fidelity vs fp32: ${fidelity.toFixed(4)}`);
  if (dtype === 'fp32' || !baseline) baseline = { dtype, docs, queryVectors };
}

if (output.precisions.fp32) {
  const base = output.precisions.fp32.metrics;
  output.deltaVsFp32 = {};
  for (const [dtype, result] of Object.entries(output.precisions)) {
    if (dtype === 'fp32') continue;
    output.deltaVsFp32[dtype] = Object.fromEntries(
      Object.keys(base).map((metric) => [metric, result.metrics[metric] - base[metric]]),
    );
  }
}

const qualityPath = path.join(ROOT, 'public', 'data', 'quality.json');
await fsp.writeFile(qualityPath, JSON.stringify(output, null, 2) + '\n');
const rawDir = path.join(ROOT, 'data', 'results');
await fsp.mkdir(rawDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
await fsp.writeFile(path.join(rawDir, `quality-${stamp}.json`), JSON.stringify(output, null, 2) + '\n');
console.log(`\nWrote ${path.relative(ROOT, qualityPath)} and data/results/quality-${stamp}.json`);
