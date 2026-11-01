import { useEffect, useMemo, useRef, useState } from 'react';
import type {
  BackendPreference,
  EvalSet,
  HealthResponse,
  InitProgress,
  PrecisionPreference,
  QualityReport,
  RuntimeInfo,
  SearchMode,
  SourceDoc,
} from './lib/types';

import { formatBytes, MODEL_DIMENSIONS, MODEL_FILES, MODEL_ID, MODEL_REVISION, QUERY_PREFIX } from './lib/model';
import {
  addDocuments,
  collectionStats,
  createCollection,
  deleteCollection,
  getHealth,
  listCollections,
  refreshIndex,
  searchDocuments,
} from './lib/api';
import { prepareDocuments } from './lib/chunk';
import { EmbeddingClient } from './lib/embedding';
import { toDocumentRecord } from './lib/records';
import { downloadJson, readStorage, writeStorage } from './lib/storage';
import { runImportBenchmark, runQueryBenchmark } from './lib/benchmark';
import type {
  ImportBenchmarkState,
  ImportState,
  QueryBenchmarkState,
  SearchParams,
  SearchState,
} from './lib/app-types';

import { RuntimePanel, type RuntimeStatus } from './components/RuntimePanel';
import { CollectionsPanel } from './components/CollectionsPanel';
import { ImportPanel } from './components/ImportPanel';
import { SearchPanel } from './components/SearchPanel';
import { QualityPanel } from './components/QualityPanel';
import { BenchmarkPanel } from './components/BenchmarkPanel';
import { EnginePanel } from './components/EnginePanel';
import { Pill } from './components/ui';

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error));

const fetchJson = async <T,>(url: string): Promise<T> => {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return (await response.json()) as T;
};

const IDLE_IMPORT: ImportState = { status: 'idle', done: 0, total: 0 };
const IDLE_SEARCH: SearchState = { status: 'idle' };

interface Notice {
  tone: 'warn' | 'error' | 'ok';
  message: string;
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState('');
  const [collections, setCollections] = useState<{ name: string; count: number | null }[]>([]);
  const [active, setActive] = useState('');
  const [count, setCount] = useState<number | null>(null);
  const [busyCollection, setBusyCollection] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>('idle');
  const [progress, setProgress] = useState<InitProgress | null>(null);
  const [runtimeError, setRuntimeError] = useState('');
  const [loadHistory, setLoadHistory] = useState<number[]>([]);
  const [backendPref, setBackendPref] = useState<BackendPreference>(() => readStorage('stepfun.backend', 'auto' as BackendPreference));
  const [precisionPref, setPrecisionPref] = useState<PrecisionPreference>(() => readStorage('stepfun.precision', 'auto' as PrecisionPreference));

  const [corpus, setCorpus] = useState<SourceDoc[]>([]);
  const [evalSet, setEvalSet] = useState<EvalSet | null>(null);
  const [quality, setQuality] = useState<QualityReport | null>(null);
  const [qualityError, setQualityError] = useState('');
  const [dataError, setDataError] = useState('');

  const [batchSize, setBatchSize] = useState(() => Math.min(Math.max(Number(readStorage('stepfun.batchSize', 8)) || 8, 1), 64));
  const [refreshEachBatch, setRefreshEachBatch] = useState(() => readStorage('stepfun.refreshEachBatch', false));
  const [importState, setImportState] = useState<ImportState>(IDLE_IMPORT);
  const [searchState, setSearchState] = useState<SearchState>(IDLE_SEARCH);
  const [queryBench, setQueryBench] = useState<QueryBenchmarkState>({ status: 'idle' });
  const [importBench, setImportBench] = useState<ImportBenchmarkState>({ status: 'idle' });

  const clientRef = useRef<EmbeddingClient | null>(null);
  const autoLoadRef = useRef(false);
  const searchWarmRef = useRef(false);
  const activeRef = useRef(active);
  activeRef.current = active;

  const getClient = () => {
    if (!clientRef.current) clientRef.current = new EmbeddingClient();
    return clientRef.current;
  };

  useEffect(() => {
    writeStorage('stepfun.backend', backendPref);
    writeStorage('stepfun.precision', precisionPref);
  }, [backendPref, precisionPref]);

  useEffect(() => {
    writeStorage('stepfun.batchSize', batchSize);
    writeStorage('stepfun.refreshEachBatch', refreshEachBatch);
  }, [batchSize, refreshEachBatch]);

  useEffect(() => {
    let cancelled = false;

    const boot = async () => {
      const [healthResult, corpusResult, evalResult, qualityResult] = await Promise.allSettled([
        getHealth(),
        fetchJson<SourceDoc[]>('/data/corpus.json'),
        fetchJson<EvalSet>('/data/eval.json'),
        fetchJson<QualityReport>('/data/quality.json'),
      ]);
      if (cancelled) return;

      if (healthResult.status === 'fulfilled') {
        const info = healthResult.value;
        setHealth(info);
        setHealthError('');
        try {
          const list = await listCollections();
          if (cancelled) return;
          setCollections(list.collections);
          const saved = readStorage('stepfun.collection', '');
          const fallback =
            list.collections.find((item) => item.name === info.defaultCollection)?.name ??
            list.collections[0]?.name ??
            info.defaultCollection;
          const next = list.collections.some((item) => item.name === saved) ? saved : fallback;
          setActive(next);
          writeStorage('stepfun.collection', next);
          const stats = await collectionStats(next);
          if (!cancelled) setCount(stats.collection.count);
        } catch (error) {
          if (!cancelled) setHealthError(errorText(error));
        }
      } else {
        setHealthError(errorText(healthResult.reason));
      }

      if (cancelled) return;

      if (corpusResult.status === 'fulfilled') {
        setCorpus(corpusResult.value);
      } else {
        setDataError(`示例语料加载失败：${errorText(corpusResult.reason)}`);
      }
      if (evalResult.status === 'fulfilled') {
        setEvalSet(evalResult.value);
      } else {
        setDataError((prev) => `${prev}${prev ? '；' : ''}评测集加载失败：${errorText(evalResult.reason)}`);
      }
      if (qualityResult.status === 'fulfilled') {
        setQuality(qualityResult.value);
        setQualityError('');
      } else {
        setQualityError(errorText(qualityResult.reason));
      }
    };

    void boot();
    return () => {
      cancelled = true;
      clientRef.current?.dispose();
      clientRef.current = null;
    };
  }, []);

  const loadModel = async (backend: BackendPreference, precision: PrecisionPreference) => {
    setRuntimeStatus('loading');
    setRuntimeError('');
    setProgress(null);
    searchWarmRef.current = false;
    try {
      const info = await getClient().init({
        backend,
        precision,
        modelId: MODEL_ID,
        onProgress: setProgress,
      });
      setRuntime(info);
      setRuntimeStatus('ready');
      setLoadHistory((history) => [...history, info.loadMs]);
      setSearchState(IDLE_SEARCH);
      setQueryBench({ status: 'idle' });
      setImportState((prev) => (prev.status === 'running' ? prev : IDLE_IMPORT));
    } catch (error) {
      setRuntimeError(errorText(error));
      setRuntimeStatus('error');
      setRuntime(null);
    }
  };

  useEffect(() => {
    if (!health?.ok || autoLoadRef.current) return;
    autoLoadRef.current = true;
    void loadModel(backendPref, precisionPref);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [health]);

  const refreshCollections = async () => {
    const list = await listCollections();
    setCollections(list.collections);
    return list;
  };

  const loadCount = async (name: string) => {
    const stats = await collectionStats(name);
    setCount(stats.collection.count);
    setCollections((items) =>
      items.map((item) => (item.name === name ? { ...item, count: stats.collection.count } : item)),
    );
    return stats.collection.count;
  };

  const selectCollection = async (name: string) => {
    setActive(name);
    activeRef.current = name;
    writeStorage('stepfun.collection', name);
    setSearchState(IDLE_SEARCH);
    setQueryBench({ status: 'idle' });
    searchWarmRef.current = false;
    await loadCount(name);
    await refreshCollections();
  };

  const handleSwitch = async (name: string) => {
    if (name === active || busyCollection) return;
    setBusyCollection(true);
    setNotice(null);
    try {
      await selectCollection(name);
    } catch (error) {
      setNotice({ tone: 'error', message: `切换集合失败：${errorText(error)}` });
    } finally {
      setBusyCollection(false);
    }
  };

  const handleCreate = async (name: string) => {
    await createCollection(name);
    await refreshCollections();
    await selectCollection(name);
    setNotice({ tone: 'ok', message: `已创建并切换到集合 ${name}` });
  };

  const handleDelete = async (name: string) => {
    if (name === active) return;
    if (!window.confirm(`确定删除集合 ${name} 及其中的全部文档与索引？此操作不可撤销。`)) return;
    setBusyCollection(true);
    try {
      await deleteCollection(name);
      await refreshCollections();
      setNotice({ tone: 'ok', message: `已删除集合 ${name}` });
    } catch (error) {
      setNotice({ tone: 'error', message: `删除集合失败：${errorText(error)}` });
    } finally {
      setBusyCollection(false);
    }
  };

  const importDocuments = async (docs: SourceDoc[], meta: { category: string; source: string }) => {
    const collectionName = activeRef.current;
    if (runtimeStatus !== 'ready') {
      setNotice({ tone: 'warn', message: '请先等待模型加载完成再导入。' });
      return;
    }
    if (!collectionName) {
      setNotice({ tone: 'warn', message: '当前没有可用集合。' });
      return;
    }

    const prepared = prepareDocuments(docs, meta);
    if (prepared.length === 0) return;

    const started = performance.now();
    let embedMs = 0;
    let writeMs = 0;
    let refreshMs = 0;
    setImportState({ status: 'running', phase: 'embedding', done: 0, total: prepared.length });
    setNotice(null);

    try {
      for (let start = 0; start < prepared.length; start += batchSize) {
        const batch = prepared.slice(start, start + batchSize);
        setImportState({ status: 'running', phase: 'embedding', done: start, total: prepared.length });

        const embedStart = performance.now();
        const embedded = await getClient().embed(
          batch.map((doc) => doc.text),
          { batchSize },
        );
        embedMs += performance.now() - embedStart;

        setImportState({ status: 'running', phase: 'writing', done: start, total: prepared.length });
        const added = await addDocuments(
          collectionName,
          batch.map((doc, offset) => toDocumentRecord(doc, embedded.vectors[offset])),
          { mode: 'upsert', refresh: refreshEachBatch },
        );
        writeMs += added.timings.writeMs;
        if (refreshEachBatch) refreshMs += added.timings.refreshMs;

        setImportState({
          status: 'running',
          phase: 'embedding',
          done: Math.min(start + batch.length, prepared.length),
          total: prepared.length,
        });
      }

      if (!refreshEachBatch) {
        setImportState({ status: 'running', phase: 'refreshing', done: prepared.length, total: prepared.length });
        const refreshed = await refreshIndex(collectionName);
        refreshMs += refreshed.timings.refreshMs;
      }

      const totalMs = performance.now() - started;
      setImportState({
        status: 'done',
        phase: 'done',
        done: prepared.length,
        total: prepared.length,
        embedMs,
        embedPerDoc: embedMs / prepared.length,
        writeMs,
        refreshMs,
        totalMs,
        count: prepared.length,
      });
      await loadCount(collectionName);
      await refreshCollections();
      setSearchState(IDLE_SEARCH);
    } catch (error) {
      setImportState({
        status: 'error',
        phase: 'embedding',
        done: 0,
        total: prepared.length,
        error: `${errorText(error)}（已写入的批次会保留，可修正后重试；重复导入使用 upsert）`,
      });
    }
  };

  const handleSearch = async (params: SearchParams) => {
    const collectionName = activeRef.current;
    if (runtimeStatus !== 'ready' || !collectionName) return;
    setSearchState({ status: 'running' });
    const started = performance.now();
    try {
      const embedStart = performance.now();
      const embedded = await getClient().embed([params.query], { batchSize: 1, prefix: QUERY_PREFIX });
      const embedMs = performance.now() - embedStart;

      const response = await searchDocuments(collectionName, {
        query: params.query,
        embedding: embedded.vectors[0],
        k: params.k,
        mode: params.mode,
        keyword: params.keyword || params.query,
        where: params.category ? { category: params.category } : undefined,
        rankWindowSize: params.rankWindowSize,
        rankConstant: params.rankConstant,
      });

      setSearchState({
        status: 'done',
        response,
        timings: {
          embedMs,
          searchMs: response.timings.searchMs,
          serverTotalMs: response.timings.serverTotalMs,
          totalMs: performance.now() - started,
          cold: !searchWarmRef.current,
        },
      });
      searchWarmRef.current = true;
    } catch (error) {
      setSearchState({ status: 'error', error: errorText(error) });
    }
  };

  const handleRunQueryBenchmark = async (config: { repetitions: number; modes: SearchMode[]; k: number }) => {
    if (!runtime || !evalSet || !active || runtimeStatus !== 'ready') return;
    if (config.modes.length === 0) return;
    setQueryBench({ status: 'running', progress: { done: 0, total: 1, label: '准备查询集' } });
    try {
      const result = await runQueryBenchmark({
        client: getClient(),
        collection: active,
        collectionCount: count ?? 0,
        corpusCount: corpus.length,
        evalSet,
        repetitions: config.repetitions,
        modes: config.modes,
        k: config.k,
        backend: runtime.device,
        dtype: runtime.dtype,
        onProgress: (progress) => setQueryBench({ status: 'running', progress }),
      });
      setQueryBench({ status: 'done', result });
    } catch (error) {
      setQueryBench({ status: 'error', error: errorText(error) });
    }
  };

  const handleRunImportBenchmark = async (config: { docCount: number }) => {
    if (!runtime || corpus.length === 0 || runtimeStatus !== 'ready') return;
    const docs = prepareDocuments(corpus.slice(0, Math.min(config.docCount, corpus.length)), {});
    if (docs.length === 0) return;
    const configs = [
      { label: '逐条嵌入 + 每批刷新（基线）', batchSize: 1, refreshEachBatch: true },
      { label: 'batch 8 + 结束时刷新', batchSize: 8, refreshEachBatch: false },
      { label: 'batch 32 + 结束时刷新（优化）', batchSize: 32, refreshEachBatch: false },
      { label: 'batch 32 + 每批刷新', batchSize: 32, refreshEachBatch: true },
    ];
    setImportBench({ status: 'running', progress: { done: 0, total: 1, label: '准备临时集合' } });
    try {
      const result = await runImportBenchmark({
        client: getClient(),
        docs,
        configs,
        backend: runtime.device,
        dtype: runtime.dtype,
        onProgress: (progress) => setImportBench({ status: 'running', progress }),
      });
      setImportBench({ status: 'done', result });
      await refreshCollections();
      await loadCount(activeRef.current);
    } catch (error) {
      setImportBench({ status: 'error', error: errorText(error) });
    }
  };

  const environment = () => ({
    userAgent: navigator.userAgent,
    hardwareConcurrency: navigator.hardwareConcurrency,
    language: navigator.language,
    model: MODEL_ID,
    revision: MODEL_REVISION,
    backend: runtime ? `${runtime.device}/${runtime.dtype}` : 'unknown',
    collection: active,
    collectionCount: count,
    corpusCount: corpus.length,
  });

  const exportQuery = () => {
    if (!queryBench.result) return;
    downloadJson(`stepfun-query-bench-${new Date().toISOString().replace(/[:.]/g, '-')}.json`, {
      ...queryBench.result,
      environment: environment(),
    });
  };

  const exportImport = () => {
    if (!importBench.result) return;
    downloadJson(`stepfun-import-bench-${new Date().toISOString().replace(/[:.]/g, '-')}.json`, {
      ...importBench.result,
      environment: environment(),
    });
  };

  const categories = useMemo(
    () =>
      Array.from(
        new Set(
          corpus
            .map((doc) => doc.category)
            .filter((value): value is string => typeof value === 'string' && value.length > 0),
        ),
      ),
    [corpus],
  );

  const modelReady = runtimeStatus === 'ready';
  const benchmarking = queryBench.status === 'running' || importBench.status === 'running';
  const searchBlocked = benchmarking || importState.status === 'running';
  const benchmarkBusy = importState.status === 'running' || searchState.status === 'running' || benchmarking;
  const importDisabled =
    !modelReady ||
    benchmarking ||
    importState.status === 'running' ||
    searchState.status === 'running' ||
    busyCollection;
  const runtimePill = runtime
    ? `${runtime.device === 'webgpu' ? 'WebGPU' : 'WASM'} · ${runtime.dtype.toUpperCase()}`
    : runtimeStatus === 'loading'
      ? '模型加载中'
      : '模型未加载';

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="#top">
            <span className="brand-mark" aria-hidden="true">
              s
            </span>
            <span className="brand-text">
              <strong>seekdb 端侧混合检索</strong>
              <small>seekdb × 阶跃星辰 · 竞赛实验台</small>
            </span>
          </a>
          <nav className="nav" aria-label="页面导航">
            <a href="#runtime">模型</a>
            <a href="#import">导入</a>
            <a href="#search">检索</a>
            <a href="#quality">质量</a>
            <a href="#benchmark">基准</a>
            <a href="#engine">引擎</a>
          </nav>
          <div className="status-group">
            <Pill tone={health?.ok ? 'ok' : healthError ? 'danger' : 'warn'}>
              {health?.ok ? 'seekdb 就绪' : healthError ? '服务离线' : '连接中'}
            </Pill>
            <Pill tone={runtime?.device === 'webgpu' ? 'ok' : runtime ? 'accent' : 'neutral'}>{runtimePill}</Pill>
            <Pill tone="neutral" title="当前集合">
              {active || '—'} · {count ?? 0}
            </Pill>
          </div>
        </div>
      </header>

      <main className="page" id="top">
        <section className="hero">
          <div className="hero-copy">
            <p className="eyebrow">题目 2 · 端侧 AI 推理性能优化与 seekdb 混合检索</p>
            <h1>
              文本在浏览器编码，
              <br />
              检索在 seekdb 完成。
            </h1>
            <p className="hero-lead">
              导入语料后，切块与嵌入全部在浏览器 Worker 内执行；向量、原文与元数据写入嵌入式 seekdb。
              查询只需一次 hybridSearch 调用，全文与 HNSW 两路召回和 RRF 融合都在数据库内完成。
            </p>
          </div>
          <div className="hero-facts">
            <div>
              <span>模型</span>
              <strong>bge-small-zh-v1.5</strong>
              <em>
                {MODEL_DIMENSIONS} 维 · BGE query prefix · {MODEL_REVISION.slice(0, 8)}
              </em>
            </div>
            <div>
              <span>量化</span>
              <strong>FP16 / INT8</strong>
              <em>
                {formatBytes(MODEL_FILES.fp16.bytes)} / {formatBytes(MODEL_FILES.int8.bytes)}
              </em>
            </div>
            <div>
              <span>引擎</span>
              <strong>seekdb 1.4 embedded</strong>
              <em>HNSW cosine + ngram2 fulltext</em>
            </div>
            <div>
              <span>融合</span>
              <strong>DBMS_HYBRID_SEARCH</strong>
              <em>RRF · 库内排序，无客户端合并</em>
            </div>
          </div>
        </section>

        {notice && (
          <div className={`notice ${notice.tone === 'error' ? 'error' : notice.tone === 'warn' ? 'warn' : 'ok'}`} role="status">
            <span>{notice.message}</span>
            <button type="button" className="icon-btn" onClick={() => setNotice(null)} aria-label="关闭提示">
              ×
            </button>
          </div>
        )}

        {healthError && (
          <div className="error-box" role="alert">
            <strong>无法连接本地 seekdb 服务</strong>
            <p>{healthError}</p>
            <p className="subtle">请在项目目录运行 npm run dev（默认 http://127.0.0.1:5173），并确认 public/models 与 public/ort 已就绪。</p>
          </div>
        )}

        {dataError && (
          <div className="notice warn" role="status">
            <span>{dataError}</span>
          </div>
        )}

        <div className="workspace">
          <aside className="rail">
            <RuntimePanel
              health={health}
              runtime={runtime}
              status={runtimeStatus}
              progress={progress}
              error={runtimeError}
              backendPref={backendPref}
              precisionPref={precisionPref}
              onBackendPref={setBackendPref}
              onPrecisionPref={setPrecisionPref}
              onLoad={() => void loadModel(backendPref, precisionPref)}
              loadHistory={loadHistory}
            />
            <CollectionsPanel
              collections={collections}
              active={active}
              count={count}
              busy={
                busyCollection ||
                importState.status === 'running' ||
                searchState.status === 'running' ||
                benchmarking
              }
              defaultName={health?.defaultCollection ?? 'kb_default'}
              onSwitch={(name) => void handleSwitch(name)}
              onCreate={handleCreate}
              onDelete={(name) => void handleDelete(name)}
            />
          </aside>

          <div className="main-col">
            <ImportPanel
              disabled={importDisabled}
              active={active || '—'}
              sampleCount={corpus.length}
              corpusReady={corpus.length > 0}
              batchSize={batchSize}
              onBatchSize={setBatchSize}
              refreshEachBatch={refreshEachBatch}
              onRefreshEachBatch={setRefreshEachBatch}
              onImport={(docs, meta) => void importDocuments(docs, meta)}
              onImportSample={() => void importDocuments(corpus, { category: '示例语料', source: 'corpus.json' })}
              state={importState}
            />
            <SearchPanel
              ready={modelReady}
              blocked={searchBlocked}
              active={active || '—'}
              count={count}
              categories={categories}
              state={searchState}
              onSearch={(params) => void handleSearch(params)}
            />
            <QualityPanel report={quality} error={qualityError} runtimeDtype={runtime?.dtype ?? null} />
            <BenchmarkPanel
              ready={modelReady}
              busy={benchmarkBusy}
              active={active || '—'}
              count={count}
              corpusCount={corpus.length}
              evalQueryCount={evalSet?.queries.length ?? 0}
              queryState={queryBench}
              importState={importBench}
              onRunQuery={(config) => void handleRunQueryBenchmark(config)}
              onRunImport={(config) => void handleRunImportBenchmark(config)}
              onExportQuery={exportQuery}
              onExportImport={exportImport}
            />
            <EnginePanel health={health} error={healthError} runtime={runtime} />
          </div>
        </div>
      </main>

      <footer className="footer">
        <span>所有向量化与检索均在本机执行 · 示例与配置不含真实凭据</span>
        <span className="mono">seekdb 1.4.0 · Transformers.js 3.8.1 · ONNX Runtime Web · {new Date().getFullYear()}</span>
      </footer>
    </div>
  );
}
