import type {
  AddDocumentsResponse,
  CollectionInfo,
  DocumentRecord,
  EngineInfo,
  HealthResponse,
  SearchMode,
  SearchResponse,
} from './types';

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { message?: string; error?: string };
      message = body.message || body.error || message;
    } catch {
      /* keep status text */
    }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/api/health');
}

export function listCollections(): Promise<{ collections: CollectionInfo[]; defaultCollection: string; engine: EngineInfo }> {
  return request('/api/collections');
}

export function createCollection(name: string): Promise<{ collection: { name: string; count: number } }> {
  return request('/api/collections', { method: 'POST', body: JSON.stringify({ name }) });
}

export function collectionStats(name: string): Promise<{ collection: { name: string; count: number; dimension: number; distance: string } }> {
  return request(`/api/collections/${encodeURIComponent(name)}/stats`);
}

export function addDocuments(
  name: string,
  documents: DocumentRecord[],
  options: { mode?: 'add' | 'upsert'; refresh?: boolean } = {},
): Promise<AddDocumentsResponse> {
  return request(`/api/collections/${encodeURIComponent(name)}/documents`, {
    method: 'POST',
    body: JSON.stringify({
      documents,
      mode: options.mode ?? 'upsert',
      refresh: options.refresh ?? false,
    }),
  });
}

export function refreshIndex(name: string): Promise<{ count: number; timings: { refreshMs: number } }> {
  return request(`/api/collections/${encodeURIComponent(name)}/refresh`, { method: 'POST', body: '{}' });
}

export function deleteCollection(name: string): Promise<{ ok: boolean }> {
  return request(`/api/collections/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export interface SearchPayload {
  query: string;
  embedding: number[];
  k: number;
  mode: SearchMode;
  where?: Record<string, string>;
  keyword?: string;
  rankWindowSize?: number;
  rankConstant?: number;
}

export function searchDocuments(name: string, payload: SearchPayload): Promise<SearchResponse> {
  return request(`/api/collections/${encodeURIComponent(name)}/search`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export { ApiError };
