/// <reference lib="webworker" />
import { env, pipeline } from '@huggingface/transformers';

import type { AdapterInfo, BackendKind, Dtype } from '../lib/types';
import type { WorkerRequest, WorkerResponse } from '../lib/worker-protocol';

const ctx = self as unknown as DedicatedWorkerGlobalScope;

env.allowRemoteModels = false;
env.allowLocalModels = true;
env.localModelPath = '/models/';
env.useBrowserCache = true;

const onnxEnv = env.backends?.onnx as unknown as
  | { wasm?: { numThreads?: number; proxy?: boolean; wasmPaths?: string } }
  | undefined;
if (onnxEnv?.wasm) {
  onnxEnv.wasm.numThreads = 1;
  onnxEnv.wasm.proxy = false;
  // Serve ORT's wasm runtime from this app instead of the default jsDelivr CDN.
  onnxEnv.wasm.wasmPaths = '/ort/';
}

interface Extractor {
  (texts: string[], options: { pooling: 'mean'; normalize: boolean }): Promise<{ tolist: () => number[][] }>;
}

let extractor: Extractor | null = null;
let loadedKey = '';

const post = (message: WorkerResponse, transfer?: Transferable[]) => {
  if (transfer && transfer.length > 0) {
    ctx.postMessage(message, transfer);
  } else {
    ctx.postMessage(message);
  }
};

const errorMessage = (error: unknown): string => {
  if (error instanceof Error) return error.message;
  return String(error);
};

async function detectWebGPU(): Promise<{ supported: boolean; reason?: string; adapter?: AdapterInfo; hasF16?: boolean }> {
  const gpu = (navigator as unknown as { gpu?: { requestAdapter: () => Promise<unknown> } }).gpu;
  if (!gpu) return { supported: false, reason: '当前浏览器未暴露 navigator.gpu' };
  try {
    const adapter = (await gpu.requestAdapter()) as
      | {
          info?: { vendor?: string; architecture?: string; device?: string; description?: string };
          features?: Iterable<string>;
        }
      | null;
    if (!adapter) return { supported: false, reason: 'requestAdapter() 未返回可用 GPU 适配器' };
    const features = adapter.features ? Array.from(adapter.features) : [];
    return {
      supported: true,
      hasF16: features.includes('shader-f16'),
      adapter: {
        vendor: adapter.info?.vendor,
        architecture: adapter.info?.architecture,
        device: adapter.info?.device,
        description: adapter.info?.description,
        features: features.slice(0, 12),
      },
    };
  } catch (error) {
    return { supported: false, reason: `WebGPU 适配器检测失败：${errorMessage(error)}` };
  }
}

async function loadPipeline(
  modelId: string,
  device: BackendKind,
  dtype: Dtype,
  onProgress: (progress: { status?: string; file?: string; progress?: number; loaded?: number; total?: number }) => void,
): Promise<Extractor> {
  return pipeline('feature-extraction', modelId, {
    device,
    dtype,
    progress_callback: (progress) => {
      const p = progress as { status?: string; file?: string; progress?: number; loaded?: number; total?: number };
      onProgress({ status: p.status, file: p.file, progress: p.progress, loaded: p.loaded, total: p.total });
    },
  }) as unknown as Promise<Extractor>;
}

async function handleInit(request: Extract<WorkerRequest, { type: 'init' }>): Promise<void> {
  const { requestId, backend, precision, modelId } = request;
  const started = performance.now();
  const webgpu = await detectWebGPU();
  let device: BackendKind = 'wasm';
  let dtype: Dtype = precision === 'auto' ? 'int8' : precision;
  let fallback = false;
  let fallbackReason: string | undefined;

  if (backend === 'webgpu') {
    if (!webgpu.supported) throw new Error(`强制 WebGPU 失败：${webgpu.reason ?? '不可用'}`);
    device = 'webgpu';
    if (precision === 'auto') dtype = 'fp16';
  } else if (backend === 'wasm') {
    device = 'wasm';
    if (precision === 'auto') dtype = 'int8';
    fallbackReason = '用户手动选择 WASM（用于验证回退路径）';
  } else if (webgpu.supported) {
    device = 'webgpu';
    if (precision === 'auto') dtype = 'fp16';
  } else {
    device = 'wasm';
    if (precision === 'auto') dtype = 'int8';
    fallback = true;
    fallbackReason = webgpu.reason;
  }

  const key = `${modelId}|${device}|${dtype}`;
  if (extractor && loadedKey === key) {
    post({
      type: 'init-done',
      requestId,
      result: {
        device,
        dtype,
        requestedBackend: backend,
        fallback,
        fallbackReason: fallbackReason ?? '复用已加载的推理会话',
        webgpuSupported: webgpu.supported,
        webgpuReason: webgpu.reason,
        adapter: webgpu.adapter,
        loadMs: performance.now() - started,
        modelId,
      },
    });
    return;
  }

  const onProgress = (progress: { status?: string; file?: string; progress?: number; loaded?: number; total?: number }) => {
    post({ type: 'init-progress', requestId, progress });
  };

  try {
    extractor = await loadPipeline(modelId, device, dtype, onProgress);
  } catch (error) {
    if (backend === 'auto' && device === 'webgpu') {
      fallback = true;
      fallbackReason = `WebGPU 会话初始化失败，已回退 WASM：${errorMessage(error)}`;
      device = 'wasm';
      dtype = precision === 'auto' ? 'int8' : precision;
      extractor = await loadPipeline(modelId, device, dtype, onProgress);
    } else {
      throw error;
    }
  }
  loadedKey = `${modelId}|${device}|${dtype}`;
  post({
    type: 'init-done',
    requestId,
    result: {
      device,
      dtype,
      requestedBackend: backend,
      fallback,
      fallbackReason,
      webgpuSupported: webgpu.supported,
      webgpuReason: webgpu.reason,
      adapter: webgpu.adapter,
      loadMs: performance.now() - started,
      modelId,
    },
  });
}

async function handleEmbed(request: Extract<WorkerRequest, { type: 'embed' }>): Promise<void> {
  const { requestId, texts, batchSize, prefix } = request;
  if (!extractor) throw new Error('模型尚未加载');
  if (!Array.isArray(texts) || texts.length === 0) {
    post({
      type: 'embed-done',
      requestId,
      result: { vectors: [], timings: { totalMs: 0, perBatchMs: [], batchSize, textCount: 0, perTextMs: 0 } },
    });
    return;
  }
  const size = Math.min(Math.max(Number(batchSize) || 1, 1), 64);
  const inputs = prefix ? texts.map((text) => `${prefix}${text}`) : texts;
  const vectors: number[][] = [];
  const perBatchMs: number[] = [];
  const started = performance.now();
  for (let start = 0; start < inputs.length; start += size) {
    const batch = inputs.slice(start, start + size);
    const batchStarted = performance.now();
    const output = (await extractor(batch, { pooling: 'mean', normalize: true })) as { tolist: () => number[][] };
    perBatchMs.push(performance.now() - batchStarted);
    const rows = output.tolist();
    for (const row of rows) vectors.push(row);
    post({ type: 'embed-progress', requestId, done: Math.min(start + size, inputs.length), total: inputs.length });
  }
  const totalMs = performance.now() - started;
  post({
    type: 'embed-done',
    requestId,
    result: {
      vectors,
      timings: {
        totalMs,
        perBatchMs,
        batchSize: size,
        textCount: texts.length,
        perTextMs: totalMs / texts.length,
      },
    },
  });
}

ctx.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const request = event.data;
  try {
    if (request.type === 'init') {
      await handleInit(request);
    } else if (request.type === 'embed') {
      await handleEmbed(request);
    }
  } catch (error) {
    const message = errorMessage(error);
    if (request.type === 'init') {
      post({ type: 'init-error', requestId: request.requestId, error: message });
    } else {
      post({ type: 'embed-error', requestId: request.requestId, error: message });
    }
  }
};
