import type { AdapterInfo, BackendKind, BackendPreference, Dtype, EmbedTimings, InitProgress, PrecisionPreference } from './types';

export interface InitRequest {
  type: 'init';
  requestId: number;
  backend: BackendPreference;
  precision: PrecisionPreference;
  modelId: string;
}

export interface EmbedRequest {
  type: 'embed';
  requestId: number;
  texts: string[];
  batchSize: number;
  prefix?: string;
}

export type WorkerRequest = InitRequest | EmbedRequest;

export interface InitProgressMessage {
  type: 'init-progress';
  requestId: number;
  progress: InitProgress;
}

export interface InitDoneMessage {
  type: 'init-done';
  requestId: number;
  result: {
    device: BackendKind;
    dtype: Dtype;
    requestedBackend: BackendPreference;
    fallback: boolean;
    fallbackReason?: string;
    webgpuSupported: boolean;
    webgpuReason?: string;
    adapter?: AdapterInfo;
    loadMs: number;
    modelId: string;
  };
}

export interface InitErrorMessage {
  type: 'init-error';
  requestId: number;
  error: string;
}

export interface EmbedProgressMessage {
  type: 'embed-progress';
  requestId: number;
  done: number;
  total: number;
}

export interface EmbedDoneMessage {
  type: 'embed-done';
  requestId: number;
  result: { vectors: number[][]; timings: EmbedTimings };
}

export interface EmbedErrorMessage {
  type: 'embed-error';
  requestId: number;
  error: string;
}

export type WorkerResponse =
  | InitProgressMessage
  | InitDoneMessage
  | InitErrorMessage
  | EmbedProgressMessage
  | EmbedDoneMessage
  | EmbedErrorMessage;
