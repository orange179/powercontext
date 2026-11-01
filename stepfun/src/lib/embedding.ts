import type { BackendPreference, EmbedResult, InitProgress, PrecisionPreference, RuntimeInfo } from './types';
import { MODEL_REVISION } from './model';
import type { WorkerRequest, WorkerResponse } from './worker-protocol';

interface PendingBase {
  resolve: (value: never) => void;
  reject: (error: Error) => void;
}

interface PendingInit extends PendingBase {
  kind: 'init';
  resolve: (value: RuntimeInfo) => void;
  onProgress?: (progress: InitProgress) => void;
}

interface PendingEmbed extends PendingBase {
  kind: 'embed';
  resolve: (value: EmbedResult) => void;
  onProgress?: (done: number, total: number) => void;
}

type Pending = PendingInit | PendingEmbed;

export class EmbeddingClient {
  private worker: Worker;
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private disposed = false;

  constructor() {
    this.worker = new Worker(new URL('../workers/embedding.worker.ts', import.meta.url), { type: 'module' });
    this.worker.addEventListener('message', this.handleMessage);
    this.worker.addEventListener('error', this.handleError);
  }

  private handleError = (event: ErrorEvent) => {
    const error = new Error(event.message || '推理 Worker 发生错误');
    for (const pending of this.pending.values()) pending.reject(error);
    this.pending.clear();
  };

  private handleMessage = (event: MessageEvent<WorkerResponse>) => {
    const message = event.data;
    const pending = this.pending.get(message.requestId);
    if (!pending) return;
    switch (message.type) {
      case 'init-progress':
        if (pending.kind === 'init') pending.onProgress?.(message.progress);
        break;
      case 'init-done':
        this.pending.delete(message.requestId);
        if (pending.kind === 'init') {
          pending.resolve({ ...message.result, modelRevision: MODEL_REVISION });
        }
        break;
      case 'init-error':
        this.pending.delete(message.requestId);
        pending.reject(new Error(message.error));
        break;
      case 'embed-progress':
        if (pending.kind === 'embed') pending.onProgress?.(message.done, message.total);
        break;
      case 'embed-done':
        this.pending.delete(message.requestId);
        if (pending.kind === 'embed') pending.resolve(message.result);
        break;
      case 'embed-error':
        this.pending.delete(message.requestId);
        pending.reject(new Error(message.error));
        break;
      default:
        break;
    }
  };

  private send(request: WorkerRequest) {
    if (this.disposed) throw new Error('推理 Worker 已释放');
    this.worker.postMessage(request);
  }

  init(options: {
    backend: BackendPreference;
    precision: PrecisionPreference;
    modelId: string;
    onProgress?: (progress: InitProgress) => void;
  }): Promise<RuntimeInfo> {
    const requestId = this.nextId++;
    return new Promise<RuntimeInfo>((resolve, reject) => {
      this.pending.set(requestId, { kind: 'init', resolve, reject, onProgress: options.onProgress });
      this.send({ type: 'init', requestId, backend: options.backend, precision: options.precision, modelId: options.modelId });
    });
  }

  embed(
    texts: string[],
    options: { batchSize: number; prefix?: string; onProgress?: (done: number, total: number) => void },
  ): Promise<EmbedResult> {
    const requestId = this.nextId++;
    return new Promise<EmbedResult>((resolve, reject) => {
      this.pending.set(requestId, { kind: 'embed', resolve, reject, onProgress: options.onProgress });
      this.send({ type: 'embed', requestId, texts, batchSize: options.batchSize, prefix: options.prefix });
    });
  }

  dispose() {
    this.disposed = true;
    this.worker.removeEventListener('message', this.handleMessage);
    this.worker.removeEventListener('error', this.handleError);
    this.worker.terminate();
    for (const pending of this.pending.values()) pending.reject(new Error('推理 Worker 已释放'));
    this.pending.clear();
  }
}
