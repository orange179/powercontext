import { useMemo, useState } from 'react';
import type {
  ImportBenchmarkState,
  LatencyStats,
  QueryBenchmarkState,
  QueryBenchMode,
} from '../lib/app-types';
import { formatMs } from '../lib/model';
import type { QualityMetricSet, SearchMode } from '../lib/types';
import { ProgressBar, Panel, Pill } from './ui';

type Tab = 'query' | 'import';

const METRIC_KEYS: (keyof QualityMetricSet)[] = ['Recall@5', 'Recall@10', 'nDCG@10', 'MRR@10'];

const latencyCells = (stats: LatencyStats) => (
  <>
    <td className="num">{stats.firstMs == null ? '-' : formatMs(stats.firstMs)}</td>
    <td className="num strong-cell">{formatMs(stats.medianMs)}</td>
    <td className="num">{formatMs(stats.p95Ms)}</td>
  </>
);

function modeRow(mode: QueryBenchMode) {
  return (
    <tr key={mode.mode}>
      <td>
        <strong>{mode.mode === 'hybrid' ? '混合检索' : '纯向量'}</strong>
        <span className="subtle"> · {mode.endToEnd.count} 次</span>
      </td>
      {latencyCells(mode.embed)}
      {latencyCells(mode.search)}
      {latencyCells(mode.endToEnd)}
      {METRIC_KEYS.map((key) => (
        <td key={key} className="num">
          {mode.metrics ? `${(mode.metrics[key] * 100).toFixed(2)}%` : '-'}
        </td>
      ))}
    </tr>
  );
}

export function BenchmarkPanel({
  ready,
  busy,
  active,
  count,
  corpusCount,
  evalQueryCount,
  queryState,
  importState,
  onRunQuery,
  onRunImport,
  onExportQuery,
  onExportImport,
}: {
  ready: boolean;
  busy: boolean;
  active: string;
  count: number | null;
  corpusCount: number;
  evalQueryCount: number;
  queryState: QueryBenchmarkState;
  importState: ImportBenchmarkState;
  onRunQuery: (config: { repetitions: number; modes: SearchMode[]; k: number }) => void;
  onRunImport: (config: { docCount: number }) => void;
  onExportQuery: () => void;
  onExportImport: () => void;
}) {
  const [tab, setTab] = useState<Tab>('query');
  const [repetitions, setRepetitions] = useState(5);
  const [modes, setModes] = useState<SearchMode[]>(['hybrid', 'vector']);
  const [docCount, setDocCount] = useState(30);

  const queryResult = queryState.result;
  const importResult = importState.result;

  const bestRunId = useMemo(() => {
    if (!importResult) return null;
    const done = importResult.runs.filter((run) => run.status === 'done');
    if (done.length === 0) return null;
    return done.reduce((best, run) => (run.totalMs < best.totalMs ? run : best), done[0]).id;
  }, [importResult]);

  const toggleMode = (mode: SearchMode) => {
    setModes((current) => {
      if (current.includes(mode)) {
        return current.length === 1 ? current : current.filter((item) => item !== mode);
      }
      return [...current, mode];
    });
  };

  return (
    <Panel
      id="benchmark"
      title="性能基准"
      subtitle="固定设备、浏览器、语料与查询集，记录后端、精度、批大小和索引刷新策略；导出原始数据可复核"
      actions={
        <div className="segmented small">
          <button type="button" className={tab === 'query' ? 'active' : ''} onClick={() => setTab('query')}>
            查询延迟
          </button>
          <button type="button" className={tab === 'import' ? 'active' : ''} onClick={() => setTab('import')}>
            导入与刷新
          </button>
        </div>
      }
    >
      {tab === 'query' && (
        <>
          <div className="control-row wrap">
            <label className="field inline">
              <span>重复次数</span>
              <select value={repetitions} onChange={(event) => setRepetitions(Number(event.target.value))}>
                {[3, 5, 10].map((value) => (
                  <option key={value} value={value}>
                    {value} 轮
                  </option>
                ))}
              </select>
            </label>
            <label className="field inline">
              <span>Top K</span>
              <input value={10} readOnly aria-readonly="true" />
            </label>
            <div className="segmented" role="group" aria-label="对比模式">
              <button
                type="button"
                className={modes.includes('hybrid') ? 'active' : ''}
                onClick={() => toggleMode('hybrid')}
                aria-pressed={modes.includes('hybrid')}
              >
                混合检索
              </button>
              <button
                type="button"
                className={modes.includes('vector') ? 'active' : ''}
                onClick={() => toggleMode('vector')}
                aria-pressed={modes.includes('vector')}
              >
                纯向量
              </button>
            </div>
            <button
              type="button"
              className="btn primary"
              disabled={!ready || busy || !count || queryState.status === 'running'}
              onClick={() => onRunQuery({ repetitions, modes, k: 10 })}
            >
              {queryState.status === 'running' ? '测量中…' : '运行查询基准'}
            </button>
            {queryResult && (
              <button type="button" className="btn ghost" onClick={onExportQuery}>
                导出原始 JSON
              </button>
            )}
          </div>

          {!ready && <p className="hint">模型加载完成后可运行基准。</p>}
          {ready && !count && <p className="hint">当前集合为空，请先导入示例语料。</p>}

          {queryState.status === 'running' && queryState.progress && (
            <ProgressBar
              value={(queryState.progress.done / Math.max(1, queryState.progress.total)) * 100}
              label={`${queryState.progress.label}（${queryState.progress.done}/${queryState.progress.total}）`}
            />
          )}

          {queryState.status === 'error' && (
            <div className="error-box" role="alert">
              <strong>基准运行失败</strong>
              <p>{queryState.error}</p>
            </div>
          )}

          {queryResult && (
            <div className="bench-result">
              <div className="bench-env">
                <span>
                  后端 <strong>{queryResult.backend.toUpperCase()}</strong> · {queryResult.dtype.toUpperCase()}
                </span>
                <span>
                  集合 <strong className="mono">{queryResult.collection}</strong>（{queryResult.collectionCount} 条）
                </span>
                <span>
                  查询 {queryResult.queryCount} 条 × {queryResult.repetitions} 轮 · Top {queryResult.k}
                </span>
                <span>示例语料 {queryResult.corpusCount} 篇</span>
                <span className="mono subtle">{new Date(queryResult.generatedAt).toLocaleString('zh-CN')}</span>
              </div>

              {queryResult.collectionCount < queryResult.corpusCount && (
                <div className="notice warn">
                  <strong>集合文档数少于示例语料</strong>
                  <span>检索指标按当前集合计算，缺失的相关文档会被计为未命中；如需对比质量，请先导入完整示例语料。</span>
                </div>
              )}

              {queryResult.warmup && (
                <div className="warmup-line">
                  <Pill tone="warn">冷路径预热</Pill>
                  <span>
                    向量化 {formatMs(queryResult.warmup.embedMs)} · seekdb {formatMs(queryResult.warmup.searchMs)} · 端到端{' '}
                    {formatMs(queryResult.warmup.totalMs)}
                  </span>
                  <span className="subtle">该次查询不计入中位数</span>
                </div>
              )}

              <div className="table-wrap">
                <table className="table benchmark-table">
                  <thead>
                    <tr>
                      <th rowSpan={2}>模式</th>
                      <th colSpan={3} className="group-head">
                        查询向量化
                      </th>
                      <th colSpan={3} className="group-head">
                        seekdb 检索
                      </th>
                      <th colSpan={3} className="group-head">
                        端到端
                      </th>
                      <th colSpan={4} className="group-head">
                        检索质量
                      </th>
                    </tr>
                    <tr>
                      <th className="num">首条</th>
                      <th className="num">中位数</th>
                      <th className="num">p95</th>
                      <th className="num">首条</th>
                      <th className="num">中位数</th>
                      <th className="num">p95</th>
                      <th className="num">首条</th>
                      <th className="num">中位数</th>
                      <th className="num">p95</th>
                      {METRIC_KEYS.map((key) => (
                        <th key={key} className="num">
                          {key}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>{queryResult.modes.map(modeRow)}</tbody>
                </table>
              </div>

              <p className="hint">{queryResult.note}</p>
            </div>
          )}

          {!queryResult && queryState.status !== 'running' && (
            <div className="empty-state">
              <strong>尚未运行查询基准</strong>
              <p>
                将在当前集合上使用固定查询集重复查询，统计冷路径、热中位数与 p95，同时用 seekdb 返回的排名计算 Recall@K、nDCG@K
                和 MRR。查询集共 {evalQueryCount} 条。
              </p>
            </div>
          )}
        </>
      )}

      {tab === 'import' && (
        <>
          <div className="control-row wrap">
            <label className="field inline">
              <span>参与对照的文档数</span>
              <select value={docCount} onChange={(event) => setDocCount(Number(event.target.value))}>
                {[12, 30, 60]
                  .filter((value) => value <= Math.max(corpusCount, 12))
                  .map((value) => (
                    <option key={value} value={value}>
                      前 {value} 篇
                    </option>
                  ))}
              </select>
            </label>
            <button
              type="button"
              className="btn primary"
              disabled={!ready || busy || corpusCount === 0 || importState.status === 'running'}
              onClick={() => onRunImport({ docCount })}
            >
              {importState.status === 'running' ? '对照中…' : '运行导入对照'}
            </button>
            {importResult && (
              <button type="button" className="btn ghost" onClick={onExportImport}>
                导出原始 JSON
              </button>
            )}
          </div>

          <p className="hint">
            四种配置依次写入独立临时集合（结束后删除）：逐条嵌入 + 每批刷新（基线）、batch 8 + 一次刷新、batch 32 + 一次刷新（优化目标）、batch
            32 + 每批刷新（刷新开销对照）。每次运行都会重新在浏览器内嵌入文档。
          </p>

          {importState.status === 'running' && importState.progress && (
            <ProgressBar
              value={(importState.progress.done / Math.max(1, importState.progress.total)) * 100}
              label={`${importState.progress.label}（${importState.progress.done}/${importState.progress.total}）`}
            />
          )}

          {importState.status === 'error' && (
            <div className="error-box" role="alert">
              <strong>导入对照失败</strong>
              <p>{importState.error}</p>
            </div>
          )}

          {importResult && (
            <div className="bench-result">
              <div className="bench-env">
                <span>
                  后端 <strong>{importResult.backend.toUpperCase()}</strong> · {importResult.dtype.toUpperCase()}
                </span>
                <span>文档 {importResult.docCount} 篇</span>
                <span className="mono subtle">{new Date(importResult.generatedAt).toLocaleString('zh-CN')}</span>
              </div>

              <div className="table-wrap">
                <table className="table benchmark-table">
                  <thead>
                    <tr>
                      <th>策略</th>
                      <th className="num">批大小</th>
                      <th className="num">刷新次数</th>
                      <th className="num">Embedding</th>
                      <th className="num">写入</th>
                      <th className="num">刷新索引</th>
                      <th className="num">端到端</th>
                      <th className="num">每条</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importResult.runs.map((run) => (
                      <tr key={run.id} className={run.id === bestRunId ? 'row-best' : undefined}>
                        <td>
                          <strong>{run.label}</strong>
                          {run.id === bestRunId && <Pill tone="ok">最快</Pill>}
                        </td>
                        <td className="num">{run.batchSize}</td>
                        <td className="num">{run.refreshCount}</td>
                        <td className="num">{formatMs(run.embedMs)}</td>
                        <td className="num">{formatMs(run.writeMs)}</td>
                        <td className="num">{formatMs(run.refreshMs)}</td>
                        <td className="num strong-cell">{formatMs(run.totalMs)}</td>
                        <td className="num">{formatMs(run.totalMs / Math.max(1, run.docCount))}</td>
                        <td>
                          {run.status === 'done' ? (
                            <span className="subtle">
                              {run.finalCount}/{run.docCount} 条
                            </span>
                          ) : (
                            <span className="field-error">{run.error ?? '未完成'}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {importResult.runs.some((run) => run.cleanupError) && (
                <div className="notice warn">
                  <strong>部分临时集合未删除</strong>
                  <span>可在「集合与会话状态」中手动删除，或重启服务后清理数据目录。</span>
                </div>
              )}

              <p className="hint">{importResult.note}</p>
            </div>
          )}

          {!importResult && importState.status !== 'running' && (
            <div className="empty-state">
              <strong>尚未运行导入对照</strong>
              <p>用同一批示例文档比较批大小与刷新策略，定位导入耗时主要花在模型推理、写入还是索引刷新上。</p>
            </div>
          )}
        </>
      )}

      <div className="bench-footnote">
        <span>
          当前集合 <strong className="mono">{active}</strong> · {count ?? 0} 条
        </span>
        <span>测量口径：重复运行取中位数与 p95；首查与热查询分开记录；原始数据包含每批次与每次查询耗时。</span>
      </div>
    </Panel>
  );
}
