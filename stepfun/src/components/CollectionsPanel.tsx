import { useState } from 'react';
import type { CollectionInfo } from '../lib/types';
import { Panel, Pill } from './ui';

export function CollectionsPanel({
  collections,
  active,
  count,
  busy,
  defaultName,
  onSwitch,
  onCreate,
  onDelete,
}: {
  collections: CollectionInfo[];
  active: string;
  count: number | null;
  busy: boolean;
  defaultName: string;
  onSwitch: (name: string) => void;
  onCreate: (name: string) => Promise<void>;
  onDelete: (name: string) => void;
}) {
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);

  const create = async () => {
    const trimmed = name.trim();
    if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(trimmed)) {
      setError('集合名需以字母开头，仅含字母、数字、下划线（≤64 字符）');
      return;
    }
    setCreating(true);
    setError('');
    try {
      await onCreate(trimmed);
      setName('');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  return (
    <Panel
      id="collections"
      title="集合与会话状态"
      subtitle="每个集合独立保存向量、原文和元数据；切换后导入与检索都作用于当前集合"
      actions={<Pill tone="accent">{active}</Pill>}
    >
      <div className="collection-list" role="list">
        {collections.map((item) => {
          const isActive = item.name === active;
          return (
            <div key={item.name} role="listitem" className={`collection-item ${isActive ? 'active' : ''}`}>
              <button
                type="button"
                className="collection-main"
                onClick={() => onSwitch(item.name)}
                disabled={busy || isActive}
                aria-pressed={isActive}
              >
                <span className="collection-name mono">{item.name}</span>
                <span className="collection-meta">
                  {isActive ? <Pill tone="accent">当前</Pill> : null}
                  <span className="subtle">{item.count ?? '…'} 条</span>
                </span>
              </button>
              {item.name !== defaultName && !isActive && (
                <button
                  type="button"
                  className="icon-btn"
                  onClick={() => onDelete(item.name)}
                  disabled={busy}
                  aria-label={`删除集合 ${item.name}`}
                  title="删除集合"
                >
                  ×
                </button>
              )}
            </div>
          );
        })}
      </div>
      <div className="inline-note">
        <span>当前集合文档数</span>
        <strong className="mono">{count ?? '—'}</strong>
      </div>
      <div className="create-row">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="新集合名，如 kb_product"
          aria-label="新集合名"
          disabled={busy || creating}
        />
        <button type="button" className="btn ghost" onClick={create} disabled={busy || creating || !name.trim()}>
          {creating ? '创建中…' : '新建'}
        </button>
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
    </Panel>
  );
}
