import { performance } from 'node:perf_hooks';
import {
  FulltextIndexConfig,
  Schema,
  SeekdbClient,
  VectorIndexConfig,
} from 'seekdb';

import { config } from './config.mjs';
import { log } from './log.mjs';

const DIM = config.dimension;

const now = () => performance.now();
const round = (ms) => Math.round(ms * 100) / 100;

function buildSchema() {
  return new Schema({
    fulltextIndex: new FulltextIndexConfig(config.fulltextAnalyzer),
    vectorIndex: new VectorIndexConfig({
      hnsw: { dimension: DIM, distance: 'cosine', type: 'hnsw' },
      embeddingFunction: null,
    }),
  });
}

function assertCollectionName(name) {
  if (typeof name !== 'string' || !config.collectionNamePattern.test(name)) {
    const err = new Error('collection name must match ^[A-Za-z][A-Za-z0-9_]{0,63}$');
    err.status = 400;
    throw err;
  }
}

function assertEmbedding(embedding, index) {
  if (!Array.isArray(embedding) || embedding.length !== DIM) {
    const err = new Error(`document[${index}].embedding must be an array of ${DIM} numbers`);
    err.status = 400;
    throw err;
  }
  for (let i = 0; i < embedding.length; i += 1) {
    if (typeof embedding[i] !== 'number' || !Number.isFinite(embedding[i])) {
      const err = new Error(`document[${index}].embedding has a non-finite value at position ${i}`);
      err.status = 400;
      throw err;
    }
  }
}

function normalizeMetadata(metadata) {
  if (metadata == null) return {};
  if (typeof metadata !== 'object' || Array.isArray(metadata)) {
    const err = new Error('metadata must be a flat object');
    err.status = 400;
    throw err;
  }
  const out = {};
  for (const [key, value] of Object.entries(metadata)) {
    if (value == null) continue;
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      out[key] = value;
    } else {
      const err = new Error(`metadata.${key} must be a string, number or boolean`);
      err.status = 400;
      throw err;
    }
  }
  return out;
}

function flatten(result) {
  const ids = result.ids?.[0] ?? [];
  const documents = result.documents?.[0] ?? [];
  const metadatas = result.metadatas?.[0] ?? [];
  const distances = result.distances?.[0] ?? [];
  return ids.map((id, rank) => ({
    id,
    text: documents[rank] ?? '',
    metadata: metadatas[rank] ?? {},
    distance: typeof distances[rank] === 'number' ? distances[rank] : null,
    rank: rank + 1,
  }));
}

export class SeekdbStore {
  constructor({ dbPath = config.dbPath } = {}) {
    this.dbPath = dbPath;
    this.client = new SeekdbClient({ path: dbPath, database: 'test' });
    this.collections = new Map();
    this.ready = false;
    this.initError = null;
  }

  async init() {
    const started = now();
    try {
      await this.client.execute('select 1');
      await this.ensureCollection(config.defaultCollection);
      this.ready = true;
      this.initMs = round(now() - started);
      log(`[seekdb] embedded engine ready at ${this.dbPath} in ${this.initMs} ms (collection ${config.defaultCollection})`);
    } catch (err) {
      this.initError = err;
      throw err;
    }
  }

  async ensureCollection(name) {
    assertCollectionName(name);
    const cached = this.collections.get(name);
    if (cached) return cached;

    const started = now();
    let collection;
    if (await this.client.hasCollection(name)) {
      collection = await this.client.getCollection({ name, embeddingFunction: null });
    } else {
      collection = await this.client.createCollection({ name, schema: buildSchema() });
    }
    this.collections.set(name, collection);
    log(`[seekdb] collection ${name} ready in ${round(now() - started)} ms`);
    return collection;
  }

  engineInfo() {
    return {
      dbPath: this.dbPath,
      dimension: DIM,
      distance: 'cosine',
      vectorIndex: 'HNSW',
      fulltextIndex: `FULLTEXT (${config.fulltextAnalyzer})`,
      hybridFusion: 'DBMS_HYBRID_SEARCH + RRF',
      initialized: this.ready,
      initMs: this.initMs ?? null,
      sdk: 'seekdb@1.4.0 (embedded / native bindings)',
    };
  }

  async listCollections() {
    const collections = await this.client.listCollections({ withEmbeddingFunction: false });
    const rows = [];
    for (const collection of collections) {
      let count = null;
      try {
        count = await collection.count();
      } catch {
        count = null;
      }
      rows.push({ name: collection.name, count });
    }
    rows.sort((a, b) => (a.name === config.defaultCollection ? -1 : b.name === config.defaultCollection ? 1 : a.name.localeCompare(b.name)));
    return rows;
  }

  async addDocuments(name, documents, { mode = 'add', refresh = true } = {}) {
    const collection = await this.ensureCollection(name);
    if (!Array.isArray(documents) || documents.length === 0) {
      const err = new Error('documents must be a non-empty array');
      err.status = 400;
      throw err;
    }
    const ids = [];
    const texts = [];
    const metadatas = [];
    const embeddings = [];
    documents.forEach((doc, i) => {
      if (!doc || typeof doc.id !== 'string' || doc.id.length === 0) {
        const err = new Error(`document[${i}].id must be a non-empty string`);
        err.status = 400;
        throw err;
      }
      if (typeof doc.text !== 'string' || doc.text.length === 0) {
        const err = new Error(`document[${i}].text must be a non-empty string`);
        err.status = 400;
        throw err;
      }
      assertEmbedding(doc.embedding, i);
      ids.push(doc.id);
      texts.push(doc.text);
      metadatas.push(normalizeMetadata(doc.metadata));
      embeddings.push(doc.embedding);
    });

    const writeStart = now();
    if (mode === 'upsert') {
      await collection.upsert({ ids, documents: texts, metadatas, embeddings });
    } else {
      await collection.add({ ids, documents: texts, metadatas, embeddings });
    }
    const writeMs = now() - writeStart;

    let refreshMs = 0;
    if (refresh) {
      const refreshStart = now();
      await collection.refresh_index();
      refreshMs = now() - refreshStart;
    }
    const count = await collection.count();
    return {
      inserted: ids.length,
      count,
      mode,
      timings: { writeMs: round(writeMs), refreshMs: round(refreshMs), totalMs: round(writeMs + refreshMs) },
    };
  }

  async deleteCollection(name) {
    assertCollectionName(name);
    if (name === config.defaultCollection) {
      const err = new Error('the default collection cannot be deleted');
      err.status = 400;
      throw err;
    }
    if (await this.client.hasCollection(name)) {
      await this.client.deleteCollection(name);
    }
    this.collections.delete(name);
    return { deleted: true };
  }

  async refresh(name) {
    const collection = await this.ensureCollection(name);
    const started = now();
    await collection.refresh_index();
    const refreshMs = now() - started;
    const count = await collection.count();
    return { count, timings: { refreshMs: round(refreshMs) } };
  }

  async stats(name) {
    const collection = await this.ensureCollection(name);
    const started = now();
    const [count, meta] = await Promise.all([collection.count(), collection.describe()]);
    const statsMs = now() - started;
    return {
      name,
      count,
      dimension: meta.dimension,
      distance: meta.distance,
      timings: { statsMs: round(statsMs) },
    };
  }

  async search(name, { query, embedding, k = 5, where, mode = 'hybrid', keyword, rankWindowSize, rankConstant }) {
    const collection = await this.ensureCollection(name);
    if (!Array.isArray(embedding) || embedding.length !== DIM) {
      const err = new Error(`embedding must be an array of ${DIM} numbers`);
      err.status = 400;
      throw err;
    }
    const nResults = Math.min(Math.max(Number(k) || 5, 1), 50);
    const queryText = typeof keyword === 'string' && keyword.trim() ? keyword.trim() : (typeof query === 'string' ? query.trim() : '');
    const filter = where && typeof where === 'object' ? where : undefined;
    const started = now();
    let result;
    let engine;
    if (mode === 'vector') {
      result = await collection.query({
        queryEmbeddings: embedding,
        nResults,
        where: filter,
        include: ['documents', 'metadatas', 'distances'],
      });
      engine = 'seekdb vector index (HNSW cosine)';
    } else {
      const rank = { rrf: {} };
      if (Number.isFinite(rankWindowSize)) rank.rrf.rankWindowSize = rankWindowSize;
      if (Number.isFinite(rankConstant)) rank.rrf.rankConstant = rankConstant;
      result = await collection.hybridSearch({
        query: {
          ...(queryText ? { whereDocument: { $contains: queryText } } : {}),
          ...(filter ? { where: filter } : {}),
          nResults,
        },
        // RRF merges both branches, so the metadata filter has to constrain the
        // vector branch as well or unfiltered KNN hits leak into the results.
        knn: { queryEmbeddings: embedding, nResults, ...(filter ? { where: filter } : {}) },
        rank,
        nResults,
        include: ['documents', 'metadatas', 'distances'],
      });
      engine = 'seekdb DBMS_HYBRID_SEARCH (fulltext + HNSW, RRF)';
    }
    const searchMs = now() - started;
    return {
      results: flatten(result),
      engine,
      mode,
      timings: { searchMs: round(searchMs), serverTotalMs: round(now() - started) },
    };
  }
}
