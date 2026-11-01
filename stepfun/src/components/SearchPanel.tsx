import { useState } from 'react';
import type { FormEvent } from 'react';
import type { SearchParams, SearchState } from '../lib/app-types';
import { formatMs } from '../lib/model';
import type { SearchMode } from '../lib/types';
import { highlightText } from '../lib/highlight';
import { EmptyState, Panel, Pill, SectionLabel } from './ui';

const K_OPTIONS = [5, 10, 20];

function distanceLabel(value: number | null): string {
  if (value == null) return 'RRF 融合';
  return `距离 ${value.toFixed(4)}`;
}

export function SearchPanel({
  ready,
  blocked,
  active,
  count,
  categories,
  state,
  onSearch,
}: {
  ready: boolean;
  blocked: boolean;
  active: string;
  count: number | null;
  categories: string[];
  state: SearchState;
  onSearch: (params: SearchParams) => void;
}) {
  const [query, setQuery] = useState('seekdb 的混合检索如何在数据库内融合向量与全文结果？');
  const [mode, setMode] = useState<SearchMode>('hybrid');
  const [k, setK] = useState(10);
  const [category, setCategory] = useState('');
  const [keyword, setKeyword] = useState('');
  const [rankWindowSize, setRankWindowSize] = useState('');
  const [rankConstant, setRankConstant] = useState('');

  const running = state.status === 'running';
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim() || running || blocked) return;
    onSearch({
      query: query.trim(),
      mode,
      k,
      category: category.trim(),
      keyword: keyword.trim(),
      rankWindowSize: rankWindowSize ? Number(rankWindowSize) : undefined,
      rankConstant: rankConstant ? Number(rankConstant) : undefined,
    });
  };

  const response = state.response;
  const timings = state.timings;

  return (
    <Panel
      id="search"
      title="混合检索"
      subtitle="查询在浏览器内完成向量化；全文与向量两路召回交给 seekdb，在库内用 RRF 融合后返回排名"
      actions={
        <>
          <Pill tone="accent">{active}</Pill>
          <Pill>{count ?? 0} 条文档</Pill>
        </>
      }
    >
      <form className="search-form" onSubmit={submit}>
        <div className="search-line">
          <input
            type="search"
            className="search-input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="输入自然语言问题，例如：增量写入后如何让新文档立刻可检索？"
            aria-label="检索问题"
            disabled={running}
          />
          <button type="submit" className="btn primary" disabled={!ready || blocked || running || !query.trim()}>
            {running ? '检索中…' : '检索'}
          </button>
        </div>

        <div className="control-row wrap">
          <div className="segmented" role="group" aria-label="检索模式">
            <button
              type="button"
              className={mode === 'hybrid' ? 'active' : ''}
              onClick={() => setMode('hybrid')}
              aria-pressed={mode === 'hybrid'}
            >
              混合检索
            </button>
            <button
              type="button"
              className={mode === 'vector' ? 'active' : ''}
              onClick={() => setMode('vector')}
              aria-pressed={mode === 'vector'}
            >
              纯向量对照
            </button>
          </div>

          <label className="field inline">
            <span>返回条数</span>
            <select value={k} onChange={(event) => setK(Number(event.target.value))}>
              {K_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  Top {value}
                </option>
              ))}
            </select>
          </label>

          <label className="field inline">
            <span>元数据过滤</span>
            <input
              list="category-options"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              placeholder="全部 category"
            />
            <datalist id="category-options">
              {categories.map((item) => (
                <option key={item} value={item} />
              ))}
            </datalist>
          </label>
        </div>

        <details className="advanced">
          <summary>高级参数（全文关键词与 RRF）</summary>
          <div className="control-row wrap">
            <label className="field">
              <span>全文关键词（留空则用问题原文）</span>
              <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="如 refresh_index" />
            </label>
            <label className="field">
              <span>rankWindowSize</span>
              <input
                type="number"
                min={1}
                max={1000}
                value={rankWindowSize}
                onChange={(event) => setRankWindowSize(event.target.value)}
                placeholder="默认"
              />
            </label>
            <label className="field">
              <span>rankConstant</span>
              <input
                type="number"
                min={1}
                max={1000}
                value={rankConstant}
                onChange={(event) => setRankConstant(event.target.value)}
                placeholder="默认"
              />
            </label>
          </div>
          <p className="hint">
            元数据过滤会随查询下推到 seekdb；全文关键词只影响全文一路，向量一路始终使用问题的嵌入。
          </p>
        </details>
      </form>

      {state.status === 'error' && (
        <div className="error-box" role="alert">
          <strong>检索失败</strong>
          <p>{state.error}</p>
        </div>
      )}

      {running && (
        <div className="search-wait" aria-live="polite">
          正在本地向量化并查询 seekdb…
        </div>
      )}

      {state.status === 'idle' && (
        <EmptyState title={count === 0 ? '当前集合还没有文档' : '提出一个问题开始检索'}>
          {count === 0
            ? '先在「导入语料」中导入示例语料或上传自己的文档；导入完成后索引会自动刷新。'
            : '问题会先在浏览器 Worker 中编码为 512 维向量，再由 seekdb 同时执行全文与 HNSW 检索。'}
        </EmptyState>
      )}

      {response && timings && (
        <>
          <div className="timing-strip">
            <div>
              <span>查询向量化</span>
              <strong>{formatMs(timings.embedMs)}</strong>
            </div>
            <div>
              <span>seekdb 检索</span>
              <strong>{formatMs(timings.searchMs)}</strong>
            </div>
            <div>
              <span>端到端</span>
              <strong>{formatMs(timings.totalMs)}</strong>
            </div>
            <div>
              <span>路径</span>
              <strong>{timings.cold ? '本次会话首查' : '热查询'}</strong>
            </div>
          </div>

          <div className="result-meta-line">
            <span className="mono">{response.engine}</span>
            <span className="subtle">
              返回 {response.results.length} 条 · {response.mode === 'hybrid' ? '全文 + HNSW 融合' : '仅 HNSW'} · 排序由 seekdb 给出
            </span>
          </div>

          {response.results.length === 0 ? (
            <EmptyState title="没有匹配结果">可尝试缩短问题、清空元数据过滤，或先导入相关文档。</EmptyState>
          ) : (
            <ol className="results">
              {response.results.map((hit) => (
                <li key={hit.id} className="result-card">
                  <div className="result-rank mono">{String(hit.rank).padStart(2, '0')}</div>
                  <div className="result-body">
                    <div className="result-head">
                      <strong>{String(hit.metadata.title ?? hit.id)}</strong>
                      <span className="mono subtle">{distanceLabel(hit.distance)}</span>
                    </div>
                    <p className="result-text">{highlightText(hit.text, query)}</p>
                    <div className="result-tags">
                      <Pill>{String(hit.metadata.category ?? '未分类')}</Pill>
                      <Pill>{String(hit.metadata.source ?? 'unknown')}</Pill>
                      {hit.metadata.lang && <Pill>{String(hit.metadata.lang)}</Pill>}
                      <span className="mono subtle">id: {hit.id}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </>
      )}

      {!ready && (
        <SectionLabel aside="加载完成后可检索">模型尚未就绪，检索按钮暂不可用。</SectionLabel>
      )}
    </Panel>
  );
}
