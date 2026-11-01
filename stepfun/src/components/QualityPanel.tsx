import type { Dtype, QualityMetricSet, QualityReport } from '../lib/types';
import { formatBytes, MODEL_SOURCE_URL } from '../lib/model';
import { Panel, Pill } from './ui';

const ORDER: Dtype[] = ['fp32', 'fp16', 'int8'];
const METRICS: (keyof QualityMetricSet)[] = ['Recall@5', 'Recall@10', 'nDCG@10', 'MRR@10'];

const pct = (value: number) => `${(value * 100).toFixed(2)}%`;
const deltaText = (value: number) => `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)} pt`;

export function QualityPanel({
  report,
  error,
  runtimeDtype,
}: {
  report: QualityReport | null;
  error: string;
  runtimeDtype: Dtype | null;
}) {
  return (
    <Panel
      id="quality"
      title="量化与检索质量"
      subtitle="固定语料与查询集，对比 FP32 / FP16 / INT8 的排序指标；量化不改变向量维度，只影响权重精度"
      actions={report ? <Pill tone="ok">离线评测已生成</Pill> : <Pill tone="warn">缺少 quality.json</Pill>}
    >
      {error && (
        <div className="error-box" role="alert">
          <strong>质量数据加载失败</strong>
          <p>{error}</p>
        </div>
      )}

      {!report && !error && (
        <div className="empty-state">
          <strong>尚未生成质量报告</strong>
          <p>
            运行 <code>npm run eval:quality</code> 会加载三种精度的 ONNX 模型，在 Node 端对固定语料与查询集排序，并生成{' '}
            <code>public/data/quality.json</code>。
          </p>
        </div>
      )}

      {report && (
        <>
          <div className="quality-head">
            <div>
              <span className="section-label">评测设置</span>
              <p>
                {report.config.corpusSize} 篇文档 · {report.config.queryCount} 条分级查询 · 指标基于余弦相似度全量排序
                （node CPU 基线，排除浏览器后端差异）。
              </p>
            </div>
            <div>
              <span className="section-label">模型</span>
              <p className="mono">
                {report.model.id} @ {report.model.revision.slice(0, 8)} · {report.model.dimensions} 维
              </p>
            </div>
          </div>

          <div className="table-wrap">
            <table className="table quality-table">
              <thead>
                <tr>
                  <th>精度</th>
                  <th className="num">模型体积</th>
                  <th className="num">压缩比</th>
                  {METRICS.map((metric) => (
                    <th key={metric} className="num">
                      {metric}
                    </th>
                  ))}
                  <th className="num">向量保真度</th>
                </tr>
              </thead>
              <tbody>
                {ORDER.map((dtype) => {
                  const row = report.precisions[dtype];
                  if (!row) return null;
                  const bytes = report.onnxSizesBytes[dtype];
                  const isCurrent = runtimeDtype === dtype;
                  return (
                    <tr key={dtype} className={isCurrent ? 'row-active' : undefined}>
                      <td>
                        <strong>{dtype.toUpperCase()}</strong>
                        {isCurrent && <Pill tone="accent">当前后端</Pill>}
                      </td>
                      <td className="num mono">{formatBytes(bytes)}</td>
                      <td className="num">{dtype === 'fp32' ? '1.00x' : `${(report.onnxSizesBytes.fp32 / bytes).toFixed(2)}x`}</td>
                      {METRICS.map((metric) => {
                        const delta = report.deltaVsFp32?.[dtype]?.[metric];
                        return (
                          <td key={metric} className="num">
                            {pct(row.metrics[metric])}
                            {delta != null && Math.abs(delta) > 0.00005 && (
                              <span className={`delta ${delta < 0 ? 'neg' : 'pos'}`}>{deltaText(delta)}</span>
                            )}
                          </td>
                        );
                      })}
                      <td className="num" title={row.vectorFidelityVsFp32 != null ? row.vectorFidelityVsFp32.toString() : undefined}>
                        {row.vectorFidelityVsFp32 == null ? '基准' : pct(row.vectorFidelityVsFp32)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="quality-notes">
            <div>
              <h3>结论</h3>
              <ul>
                <li>
                  FP16 体积为 FP32 的 {(report.onnxSizesBytes.fp32 / report.onnxSizesBytes.fp16).toFixed(2)} 倍压缩，四项指标与
                  FP32 完全一致，是 WebGPU 默认精度。
                </li>
                <li>
                  INT8 体积为 FP32 的 {(report.onnxSizesBytes.fp32 / report.onnxSizesBytes.int8).toFixed(2)} 倍压缩；nDCG@10 下降
                  {Math.abs((report.deltaVsFp32?.int8?.['nDCG@10'] ?? 0) * 100).toFixed(2)} 个百分点，Recall@5 下降{' '}
                  {Math.abs((report.deltaVsFp32?.int8?.['Recall@5'] ?? 0) * 100).toFixed(2)} 个百分点，用于 WASM 默认精度。
                </li>
                <li>「向量保真度」是量化模型与 FP32 对同一批文档的向量平均余弦相似度。</li>
              </ul>
            </div>
            <div>
              <h3>复现</h3>
              <p>
                <code>npm run fetch:models -- --all</code> 下载三种 ONNX 权重并校验字节数；
                <code>npm run eval:quality</code> 重新生成质量报告与带时间戳的原始结果。
              </p>
              <p className="subtle">
                质量评测独立于浏览器后端。浏览器内的 seekdb 路径指标可在下方「性能基准 → 查询延迟」中重算。
              </p>
              <a href={MODEL_SOURCE_URL} target="_blank" rel="noreferrer" className="link">
                模型来源与版本
              </a>
            </div>
          </div>
        </>
      )}
    </Panel>
  );
}
