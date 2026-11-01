import { useRef, useState } from 'react';
import { parseFile, parseTextInput } from '../lib/chunk';
import type { SourceDoc } from '../lib/types';
import { formatMs } from '../lib/model';
import { Panel, Pill, ProgressBar, Stat } from './ui';
import type { ImportState } from '../lib/app-types';

const BATCH_SIZES = [1, 4, 8, 16, 32];

export function ImportPanel({
  disabled,
  active,
  sampleCount,
  corpusReady,
  batchSize,
  onBatchSize,
  refreshEachBatch,
  onRefreshEachBatch,
  onImport,
  onImportSample,
  state,
}: {
  disabled: boolean;
  active: string;
  sampleCount: number;
  corpusReady: boolean;
  batchSize: number;
  onBatchSize: (value: number) => void;
  refreshEachBatch: boolean;
  onRefreshEachBatch: (value: boolean) => void;
  onImport: (docs: SourceDoc[], meta: { category: string; source: string }) => void;
  onImportSample: () => void;
  state: ImportState;
}) {
  const [category, setCategory] = useState('自定义');
  const [source, setSource] = useState('local-upload');
  const [paste, setPaste] = useState('');
  const [showPaste, setShowPaste] = useState(false);
  const [fileError, setFileError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const running = state.status === 'running';
  const percent = state.total > 0 ? (state.done / state.total) * 100 : 0;
  const phaseText: Record<string, string> = {
    embedding: '浏览器本地向量化',
    writing: '写入 seekdb',
    refreshing: '刷新向量索引',
    done: '完成',
  };

  const acceptFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setFileError('');
    const docs: SourceDoc[] = [];
    try {
      for (const file of Array.from(files)) {
        const content = await file.text();
        const parsed = parseFile(file.name, content);
        if (parsed.length === 0) {
          setFileError(`文件 ${file.name} 未解析出文本`);
        }
        docs.push(...parsed.map((doc) => ({ ...doc, source: doc.source || file.name })));
      }
      if (docs.length > 0) onImport(docs, { category, source });
    } catch (err) {
      setFileError(err instanceof Error ? err.message : String(err));
    } finally {
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const importPaste = () => {
    const docs = parseTextInput(paste);
    if (docs.length === 0) return;
    onImport(docs, { category, source: source || 'paste' });
    setPaste('');
  };

  return (
    <Panel
      id="import"
      title="导入语料"
      subtitle={`写入集合 ${active}；切块、向量化、写库、刷新索引均在本地完成`}
      actions={<Pill>{sampleCount} 篇示例</Pill>}
    >
      <div className="control-row wrap">
        <label className="field">
          <span>元数据 category</span>
          <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="如 产品手册" disabled={running} />
        </label>
        <label className="field">
          <span>元数据 source</span>
          <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="如 handbook.md" disabled={running} />
        </label>
      </div>

      <div className="control-row wrap">
        <label className="field">
          <span>向量化批大小</span>
          <select value={batchSize} onChange={(e) => onBatchSize(Number(e.target.value))} disabled={running}>
            {BATCH_SIZES.map((size) => (
              <option key={size} value={size}>
                batch = {size}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={refreshEachBatch}
            onChange={(e) => onRefreshEachBatch(e.target.checked)}
            disabled={running}
          />
          <span>每批写入后刷新（对照用；默认只在结束时刷新一次）</span>
        </label>
      </div>

      <div className="button-row">
        <button type="button" className="btn primary" onClick={onImportSample} disabled={disabled || running || !corpusReady}>
          {running ? '导入中…' : `导入示例语料（${sampleCount} 篇）`}
        </button>
        <label className="btn ghost file-btn">
          上传文件（txt / md / json / csv）
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.md,.markdown,.json,.csv,text/plain,text/markdown,application/json"
            multiple
            onChange={(e) => acceptFiles(e.target.files)}
            disabled={disabled || running}
          />
        </label>
        <button type="button" className="btn ghost" onClick={() => setShowPaste((v) => !v)} disabled={running}>
          {showPaste ? '收起粘贴框' : '粘贴文本'}
        </button>
      </div>

      {showPaste && (
        <div className="paste-box">
          <textarea
            value={paste}
            onChange={(e) => setPaste(e.target.value)}
            rows={5}
            placeholder="粘贴文本，空行分段；# 标题 会作为文档标题"
            disabled={disabled || running}
          />
          <button type="button" className="btn ghost" onClick={importPaste} disabled={disabled || running || !paste.trim()}>
            导入粘贴内容
          </button>
        </div>
      )}

      {fileError && <p className="field-error" role="alert">{fileError}</p>}

      {running && (
        <div className="load-progress" aria-live="polite">
          <ProgressBar value={percent} label={`${phaseText[state.phase ?? 'embedding']}：${state.done}/${state.total}`} />
          <span className="mono subtle">{Math.round(percent)}%</span>
        </div>
      )}

      {state.status === 'error' && (
        <div className="error-box" role="alert">
          <strong>导入失败</strong>
          <p>{state.error}</p>
        </div>
      )}

      {state.status === 'done' && (
        <div className="import-summary" aria-live="polite">
          <div className="stat-grid">
            <Stat label="文档块" value={state.count ?? 0} hint={`批大小 ${batchSize}`} />
            <Stat label="向量化" value={formatMs(state.embedMs)} hint={`${formatMs(state.embedPerDoc)}/条`} />
            <Stat label="写入" value={formatMs(state.writeMs)} hint="seekdb add/upsert" />
            <Stat label="刷新索引" value={formatMs(state.refreshMs)} hint={refreshEachBatch ? '每批刷新' : '结束时一次'} />
            <Stat label="端到端" value={formatMs(state.totalMs)} hint="不含模型加载" tone="ok" />
          </div>
        </div>
      )}

      <p className="hint">
        示例语料含有明确相关标注，可直接用于下方「检索质量」与「性能基准」。重复导入使用 upsert，按确定性文档 ID 更新，不会产生重复行。
      </p>
    </Panel>
  );
}
