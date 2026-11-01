import type { BackendPreference, HealthResponse, InitProgress, PrecisionPreference, RuntimeInfo } from '../lib/types';
import { formatBytes, formatMs, MODEL_FILES, MODEL_ID, MODEL_REVISION, MODEL_SOURCE_URL } from '../lib/model';
import { Panel, Pill, ProgressBar, Stat } from './ui';

export type RuntimeStatus = 'idle' | 'loading' | 'ready' | 'error';

const backendLabel: Record<BackendPreference, string> = {
  auto: '自动（优先 WebGPU）',
  webgpu: '强制 WebGPU',
  wasm: '强制 WASM（回退验证）',
};

const precisionLabel: Record<PrecisionPreference, string> = {
  auto: '自动（WebGPU→FP16 / WASM→INT8）',
  fp16: 'FP16',
  int8: 'INT8',
  fp32: 'FP32（需本地文件）',
};

function runtimePill(status: RuntimeStatus, runtime: RuntimeInfo | null) {
  if (status === 'loading') return <Pill tone="warn">模型加载中</Pill>;
  if (status === 'error') return <Pill tone="danger">推理不可用</Pill>;
  if (!runtime) return <Pill>未加载</Pill>;
  const label = `${runtime.device === 'webgpu' ? 'WebGPU' : 'WASM'} · ${runtime.dtype.toUpperCase()}`;
  return <Pill tone={runtime.device === 'webgpu' ? 'ok' : 'accent'}>{label}</Pill>;
}

export function RuntimePanel({
  health,
  runtime,
  status,
  progress,
  error,
  backendPref,
  precisionPref,
  onBackendPref,
  onPrecisionPref,
  onLoad,
  loadHistory,
}: {
  health: HealthResponse | null;
  runtime: RuntimeInfo | null;
  status: RuntimeStatus;
  progress: InitProgress | null;
  error: string;
  backendPref: BackendPreference;
  precisionPref: PrecisionPreference;
  onBackendPref: (value: BackendPreference) => void;
  onPrecisionPref: (value: PrecisionPreference) => void;
  onLoad: () => void;
  loadHistory: number[];
}) {
  const percent = progress?.progress != null ? Math.round(progress.progress) : null;
  return (
    <Panel
      id="runtime"
      title="模型与运行后端"
      subtitle="文本向量化完全在浏览器内执行，模型与 ORT 运行时均由本地服务托管"
      actions={runtimePill(status, runtime)}
    >
      <div className="control-row">
        <label className="field">
          <span>执行后端</span>
          <select value={backendPref} onChange={(e) => onBackendPref(e.target.value as BackendPreference)} disabled={status === 'loading'}>
            {Object.entries(backendLabel).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>模型精度</span>
          <select value={precisionPref} onChange={(e) => onPrecisionPref(e.target.value as PrecisionPreference)} disabled={status === 'loading'}>
            {Object.entries(precisionLabel).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn primary" onClick={onLoad} disabled={status === 'loading' || !health?.ok}>
          {status === 'loading' ? '加载中…' : runtime ? '重新加载模型' : '加载模型'}
        </button>
      </div>

      {status === 'loading' && (
        <div className="load-progress">
          <ProgressBar value={percent ?? 0} label={progress?.file ? `下载/初始化：${progress.file}` : '正在创建推理会话…'} />
          <span className="mono subtle">{percent != null ? `${percent}%` : '初始化'}</span>
        </div>
      )}

      {status === 'error' && (
        <div className="error-box" role="alert">
          <strong>模型加载失败</strong>
          <p>{error}</p>
          <p className="subtle">可切换到「强制 WASM」后重新加载，或检查 public/models 与 public/ort 是否完整。</p>
        </div>
      )}

      {runtime && status === 'ready' && (
        <>
          <div className="stat-grid">
            <Stat label="当前后端" value={runtime.device === 'webgpu' ? 'WebGPU' : 'WASM'} hint={runtime.dtype.toUpperCase()} tone={runtime.device === 'webgpu' ? 'ok' : undefined} />
            <Stat label="加载耗时" value={formatMs(runtime.loadMs)} hint={loadHistory.length > 1 ? `首次 ${formatMs(loadHistory[0])}` : '冷加载'} />
            <Stat label="WebGPU 检测" value={runtime.webgpuSupported ? '可用' : '不可用'} hint={runtime.adapter?.vendor || runtime.webgpuReason || '-'} />
            <Stat label="模型维度" value="512" hint={MODEL_ID.split('/')[1]} />
          </div>

          {runtime.fallback && (
            <div className="notice warn" role="status">
              <strong>已自动回退到 WASM</strong>
              <span>{runtime.fallbackReason || 'WebGPU 不可用'}</span>
            </div>
          )}
          {!runtime.fallback && runtime.fallbackReason && (
            <div className="notice">
              <strong>运行路径说明</strong>
              <span>{runtime.fallbackReason}</span>
            </div>
          )}

          {(runtime.adapter || runtime.webgpuReason) && (
            <dl className="kv">
              <div>
                <dt>GPU 适配器</dt>
                <dd>{runtime.adapter ? [runtime.adapter.vendor, runtime.adapter.architecture, runtime.adapter.description].filter(Boolean).join(' · ') || '已获取适配器' : runtime.webgpuReason}</dd>
              </div>
              {runtime.adapter?.features && (
                <div>
                  <dt>GPU 特性</dt>
                  <dd className="mono">{runtime.adapter.features.slice(0, 6).join(', ')}</dd>
                </div>
              )}
              <div>
                <dt>模型版本</dt>
                <dd className="mono">{MODEL_ID} @ {MODEL_REVISION.slice(0, 8)}</dd>
              </div>
            </dl>
          )}
        </>
      )}

      <div className="model-sizes">
        <div className="section-label">
          <span>量化对照（实际文件字节）</span>
          <a href={MODEL_SOURCE_URL} target="_blank" rel="noreferrer">
            模型来源
          </a>
        </div>
        <table className="table compact">
          <thead>
            <tr>
              <th>精度</th>
              <th>文件</th>
              <th className="num">体积</th>
              <th className="num">相对 FP32</th>
            </tr>
          </thead>
          <tbody>
            {(['fp32', 'fp16', 'int8'] as const).map((dtype) => {
              const bytes = MODEL_FILES[dtype].bytes;
              const ratio = MODEL_FILES.fp32.bytes / bytes;
              return (
                <tr key={dtype} className={runtime?.dtype === dtype ? 'row-active' : undefined}>
                  <td>{dtype.toUpperCase()}</td>
                  <td className="mono subtle">{MODEL_FILES[dtype].file.split('/')[1]}</td>
                  <td className="num">{formatBytes(bytes)}</td>
                  <td className="num">{dtype === 'fp32' ? '1.00x' : `${ratio.toFixed(2)}x 压缩`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="hint">FP32 基线文件不随仓库提交，可用 <code>npm run fetch:models -- --all</code> 下载；量化质量数据见「检索质量」。</p>
      </div>
    </Panel>
  );
}
