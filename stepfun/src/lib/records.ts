import type { DocumentRecord, PreparedDoc } from './types';

export function toDocumentRecord(doc: PreparedDoc, embedding: number[]): DocumentRecord {
  return {
    id: doc.id,
    text: doc.text,
    embedding,
    metadata: {
      title: doc.title,
      category: doc.category,
      source: doc.source,
      lang: doc.lang,
      chunk: doc.chunk,
      totalChunks: doc.totalChunks,
    },
  };
}
