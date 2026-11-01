export type BackendKind = 'webgpu' | 'wasm';
export type Dtype = 'fp16' | 'int8' | 'fp32';
export type BackendPreference = 'auto' | 'webgpu' | 'wasm';
export type PrecisionPreference = 'auto' | Dtype;
export type SearchMode = 'hybrid' | 'vector';

export interface AdapterInfo {
  vendor?: string;
  architecture?: string;
  device?: string;
  description?: string;
  features?: string[];
}

export interface RuntimeInfo {
  device: BackendKind;
  dtype: Dtype;
  requestedBackend: BackendPreference;
  fallback: boolean;
  fallbackReason?: string;
  webgpuSupported: boolean;
  webgpuReason?: string;
  adapter?: AdapterInfo;
  loadMs: number;
  modelId: string;
  modelRevision: string;
}

export interface InitProgress {
  status?: string;
  file?: string;
  progress?: number;
  loaded?: number;
  total?: number;
}

export interface EmbedTimings {
  totalMs: number;
  perBatchMs: number[];
  batchSize: number;
  textCount: number;
  perTextMs: number;
}

export interface EmbedResult {
  vectors: number[][];
  timings: EmbedTimings;
}

export interface SourceDoc {
  id?: string;
  text: string;
  title?: string;
  category?: string;
  source?: string;
  lang?: string;
}

export interface PreparedDoc {
  id: string;
  text: string;
  title: string;
  category: string;
  source: string;
  lang: string;
  chunk: number;
  totalChunks: number;
}

export interface DocumentRecord {
  id: string;
  text: string;
  metadata: Record<string, string | number | boolean>;
  embedding: number[];
}

export interface SearchHit {
  id: string;
  text: string;
  metadata: Record<string, string | number | boolean>;
  distance: number | null;
  rank: number;
}

export interface SearchResponse {
  results: SearchHit[];
  engine: string;
  mode: SearchMode;
  timings: { searchMs: number; serverTotalMs: number };
}

export interface CollectionInfo {
  name: string;
  count: number | null;
}

export interface EngineInfo {
  dbPath: string;
  dimension: number;
  distance: string;
  vectorIndex: string;
  fulltextIndex: string;
  hybridFusion: string;
  initialized: boolean;
  initMs: number | null;
  sdk: string;
}

export interface HealthResponse {
  ok: boolean;
  engine: EngineInfo;
  defaultCollection: string;
  node: string;
  platform: string;
}

export interface AddDocumentsResponse {
  inserted: number;
  count: number;
  mode: 'add' | 'upsert';
  timings: { writeMs: number; refreshMs: number; totalMs: number };
}

export interface QueryEval {
  id: string;
  query: string;
  relevant: { id: string; grade: number }[];
}

export interface EvalSet {
  name: string;
  version: string;
  language: string;
  method: string;
  queries: QueryEval[];
}

export interface QualityMetricSet {
  'Recall@5': number;
  'Recall@10': number;
  'nDCG@10': number;
  'MRR@10': number;
}

export interface QualityPrecisionResult {
  metrics: QualityMetricSet;
  vectorFidelityVsFp32: number | null;
  timings: { loadMs: number; documentEmbeddingMs: number; queryEmbeddingMs: number; documentEmbeddingMsPerDoc: number };
  perQuery: { id: string; query: string; top10: string[] }[];
}

export interface QualityReport {
  generatedAt: string;
  model: { id: string; revision: string; dimensions: number; queryPrefix: string; source: string };
  config: { corpusSize: number; queryCount: number; topK: number; metrics: string };
  onnxSizesBytes: Record<string, number>;
  precisions: Record<string, QualityPrecisionResult>;
  deltaVsFp32?: Record<string, Partial<QualityMetricSet>>;
}
