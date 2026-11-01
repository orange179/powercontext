import type {
  QualityMetricSet,
  SearchMode,
  SearchResponse,
} from './types';

export interface ImportState {
  status: 'idle' | 'running' | 'done' | 'error';
  phase?: 'embedding' | 'writing' | 'refreshing' | 'done';
  done: number;
  total: number;
  embedMs?: number;
  embedPerDoc?: number;
  writeMs?: number;
  refreshMs?: number;
  totalMs?: number;
  count?: number;
  error?: string;
}

export interface SearchTimings {
  embedMs: number;
  searchMs: number;
  serverTotalMs: number;
  totalMs: number;
  cold: boolean;
}

export interface SearchState {
  status: 'idle' | 'running' | 'done' | 'error';
  response?: SearchResponse;
  timings?: SearchTimings;
  error?: string;
}

export interface SearchParams {
  query: string;
  k: number;
  mode: SearchMode;
  category: string;
  keyword: string;
  rankWindowSize?: number;
  rankConstant?: number;
}

export interface LatencyStats {
  firstMs: number | null;
  medianMs: number;
  meanMs: number;
  p95Ms: number;
  minMs: number;
  maxMs: number;
  count: number;
}

export interface QueryBenchSample {
  mode: SearchMode;
  queryId: string;
  query: string;
  rep: number;
  embedMs: number;
  searchMs: number;
  totalMs: number;
  topIds: string[];
}

export interface QueryBenchMode {
  mode: SearchMode;
  embed: LatencyStats;
  search: LatencyStats;
  endToEnd: LatencyStats;
  metrics: QualityMetricSet | null;
  samples: QueryBenchSample[];
}

export interface QueryBenchmarkResult {
  generatedAt: string;
  backend: string;
  dtype: string;
  collection: string;
  collectionCount: number;
  corpusCount: number;
  k: number;
  repetitions: number;
  queryCount: number;
  warmup: { embedMs: number; searchMs: number; totalMs: number } | null;
  modes: QueryBenchMode[];
  note: string;
}

export interface QueryBenchmarkState {
  status: 'idle' | 'running' | 'done' | 'error';
  progress?: { done: number; total: number; label: string };
  result?: QueryBenchmarkResult;
  error?: string;
}

export interface ImportBenchRun {
  id: string;
  label: string;
  batchSize: number;
  refreshEachBatch: boolean;
  docCount: number;
  embedMs: number;
  writeMs: number;
  refreshMs: number;
  totalMs: number;
  perBatchEmbedMs: number[];
  perBatchWriteMs: number[];
  perBatchRefreshMs: number[];
  batchCount: number;
  refreshCount: number;
  finalCount: number;
  status: 'pending' | 'running' | 'done' | 'error';
  error?: string;
  cleanupError?: string;
}

export interface ImportBenchmarkResult {
  generatedAt: string;
  backend: string;
  dtype: string;
  docCount: number;
  runs: ImportBenchRun[];
  note: string;
}

export interface ImportBenchmarkState {
  status: 'idle' | 'running' | 'done' | 'error';
  progress?: { done: number; total: number; label: string };
  result?: ImportBenchmarkResult;
  error?: string;
}

export interface CollectionSnapshot {
  token: number;
  name: string;
  count: number | null;
}
