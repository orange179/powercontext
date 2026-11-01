import type { HealthResponse, RuntimeInfo } from '../lib/types';
import { formatMs, MODEL_ID, MODEL_REVISION } from '../lib/model';
import { Panel, Pill, Stat } from './ui';

const SCHEMA_SNIPPET = `new Schema({
  fulltextIndex: new FulltextIndexConfig('ngram2'),
  vectorIndex: new VectorIndexConfig({
    hnsw: { dimension: 512, distance: 'cosine', type: 'hnsw' },
    embeddingFunction: null,
  }),
})`;

export function EnginePanel({
  health,
  error,
  runtime,
}: {
  health: HealthResponse | null;
  error: string;
  runtime: RuntimeInfo | null;
}) {
  const engine = health?.engine;

  return (
    <Panel
      id="engine"
      title="引擎配置与合规说明"
      subtitle="嵌入式 seekdb 随本地服务进程启动；浏览器只负责向量化与渲染，不合并任何检索结果"
      actions={engine?.initialized ? <Pill tone="ok">seekdb 就绪</Pill> : <Pill tone="warn">等待引擎</Pill>}
    >
      {error && (
        <div className="error-box" role="alert">
          <strong>本地服务不可达</strong>
          <p>{error}</p>
        </div>
      )}

      {health && engine && (
        <>
          <div className="stat-grid engine-stats">
            <Stat label="集合维度" value={engine.dimension} hint={`${engine.distance} 距离`} />
            <Stat label="向量索引" value={engine.vectorIndex} hint={`${MODEL_ID.split('/')[1]} · 512d`} />
            <Stat label="全文索引" value="ngram2" hint="FULLTEXT 内置分词" />
            <Stat label="融合方式" value="RRF" hint="库内 DBMS_HYBRID_SEARCH" />
            <Stat label="引擎启动" value={formatMs(engine.initMs)} hint={health.node} />
          </div>

          <div className="engine-grid">
            <div>
              <h3>数据流</h3>
              <ol className="flow-list">
                <li>
                  <strong>文档向量化</strong>
                  <span>浏览器 Web Worker 内加载 {MODEL_ID}，本地执行 ONNX 推理；文本不离开设备。</span>
                </li>
                <li>
                  <strong>写入 seekdb</strong>
                  <span>向量、原文、元数据通过本地 API 写入嵌入式 seekdb 集合。</span>
                </li>
                <li>
                  <strong>索引刷新</strong>
                  <span>导入结束后调用 refresh_index，增量文档立即可被检索。</span>
                </li>
                <li>
                  <strong>查询与融合</strong>
                  <span>查询向量化后只调用一次 hybridSearch；全文与 HNSW 两路召回及 RRF 融合都在 seekdb 内完成。</span>
                </li>
              </ol>
            </div>

            <div>
              <h3>集合 Schema</h3>
              <pre className="code">{SCHEMA_SNIPPET}</pre>
              <dl className="kv">
                <div>
                  <dt>数据目录</dt>
                  <dd className="mono">{engine.dbPath}</dd>
                </div>
                <div>
                  <dt>SDK</dt>
                  <dd>{engine.sdk}</dd>
                </div>
                <div>
                  <dt>模型版本</dt>
                  <dd className="mono">{MODEL_REVISION}</dd>
                </div>
                <div>
                  <dt>本机环境</dt>
                  <dd>
                    {health.platform} · Node {health.node}
                  </dd>
                </div>
              </dl>
            </div>
          </div>
        </>
      )}

      <div className="compliance">
        <h3>合规自检</h3>
        <ul>
          <li>
            <Pill tone="ok">无云端推理</Pill>
            模型文件由本服务托管，浏览器禁止远程模型加载（allowRemoteModels=false）。
          </li>
          <li>
            <Pill tone="ok">无预计算回放</Pill>
            每次查询都重新执行浏览器向量化与 seekdb 检索，结果不缓存、不读取固定答案。
          </li>
          <li>
            <Pill tone="ok">唯一检索通道</Pill>
            向量与原文只写入 seekdb；检索排序由 seekdb 返回，前端不做结果合并或内存检索。
          </li>
          <li>
            <Pill tone="ok">运行后端可见</Pill>
            当前后端为 {runtime ? `${runtime.device.toUpperCase()} · ${runtime.dtype.toUpperCase()}` : '尚未加载'}
            ，WebGPU 不可用时自动回退到 WASM 并在界面标注。
          </li>
        </ul>
        <p className="hint">
          示例与配置中不包含任何真实密钥。服务默认只监听 127.0.0.1，数据目录位于项目内，可随时删除后重新导入。
        </p>
      </div>
    </Panel>
  );
}
