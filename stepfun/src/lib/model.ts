export const MODEL_ID = 'Xenova/bge-small-zh-v1.5';
export const MODEL_REVISION = '75c43b069aac4d136ba6bc1122f995fedcfd2781';
export const MODEL_DIMENSIONS = 512;
export const QUERY_PREFIX = '为这个句子生成表示以用于检索相关文章：';
export const MODEL_FILES = {
  fp32: { file: 'onnx/model.onnx', bytes: 94851877 },
  fp16: { file: 'onnx/model_fp16.onnx', bytes: 47497427 },
  int8: { file: 'onnx/model_int8.onnx', bytes: 23903394 },
} as const;

export const MODEL_SOURCE_URL = `https://huggingface.co/${MODEL_ID}/tree/${MODEL_REVISION}`;

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return '-';
  const mib = bytes / 1048576;
  return `${mib.toFixed(2)} MiB`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return '-';
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 1000) return `${ms.toFixed(1)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}
