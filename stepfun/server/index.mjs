import http from 'node:http';
import path from 'node:path';
import fs from 'node:fs';
import express from 'express';

import { config, ROOT } from './config.mjs';
import { log, logError } from './log.mjs';
import { SeekdbStore } from './seekdb-store.mjs';

const app = express();
const store = new SeekdbStore({ dbPath: config.dbPath });

app.use(express.json({ limit: '32mb' }));

app.use((req, res, next) => {
  if (!req.path.startsWith('/api/')) return next();
  const started = Date.now();
  res.on('finish', () => {
    log(`[api] ${req.method} ${req.originalUrl} -> ${res.statusCode} (${Date.now() - started} ms)`);
  });
  next();
});

const wrap = (handler) => (req, res, next) => Promise.resolve(handler(req, res, next)).catch(next);

app.get('/api/health', (req, res) => {
  res.json({
    ok: store.ready,
    engine: store.engineInfo(),
    defaultCollection: config.defaultCollection,
    node: process.version,
    platform: `${process.platform}-${process.arch}`,
  });
});

app.get('/api/collections', wrap(async (req, res) => {
  const collections = await store.listCollections();
  res.json({ collections, defaultCollection: config.defaultCollection, engine: store.engineInfo() });
}));

app.post('/api/collections', wrap(async (req, res) => {
  const name = req.body?.name;
  await store.ensureCollection(name);
  const stats = await store.stats(name);
  res.status(201).json({ collection: stats, engine: store.engineInfo() });
}));

app.get('/api/collections/:name/stats', wrap(async (req, res) => {
  res.json({ collection: await store.stats(req.params.name) });
}));

app.post('/api/collections/:name/documents', wrap(async (req, res) => {
  const { documents, mode, refresh } = req.body ?? {};
  const result = await store.addDocuments(req.params.name, documents, {
    mode: mode === 'upsert' ? 'upsert' : 'add',
    refresh: refresh !== false,
  });
  res.json(result);
}));

app.delete('/api/collections/:name', wrap(async (req, res) => {
  res.json(await store.deleteCollection(req.params.name));
}));

app.post('/api/collections/:name/refresh', wrap(async (req, res) => {
  res.json(await store.refresh(req.params.name));
}));

app.post('/api/collections/:name/search', wrap(async (req, res) => {
  const { query, embedding, k, where, mode, keyword, rankWindowSize, rankConstant } = req.body ?? {};
  const result = await store.search(req.params.name, {
    query, embedding, k, where, mode, keyword, rankWindowSize, rankConstant,
  });
  res.json(result);
}));

app.use((err, req, res, next) => {
  const status = err.status && Number.isInteger(err.status) ? err.status : 500;
  logError(`[error] ${req.method} ${req.originalUrl}`, err?.stack || err);
  res.status(status).json({
    error: err.code || (status === 400 ? 'BAD_REQUEST' : 'INTERNAL_ERROR'),
    message: err.message || String(err),
  });
});

async function start() {
  const httpServer = http.createServer(app);

  if (config.isDev) {
    // ONNX Runtime dynamically imports its wasm glue from /ort; Vite refuses to
    // transform files inside public/, so serve the runtime ahead of Vite.
    app.use('/ort', express.static(path.join(ROOT, 'public', 'ort')));
    const { createServer } = await import('vite');
    const vite = await createServer({
      root: ROOT,
      server: { middlewareMode: true, hmr: { server: httpServer } },
      appType: 'spa',
    });
    app.use(vite.middlewares);
    log('[server] Vite middleware enabled (development)');
  } else {
    const dist = path.join(ROOT, 'dist');
    if (!fs.existsSync(path.join(dist, 'index.html'))) {
      logError('[server] dist/index.html not found. Run `npm run build` first.');
      process.exit(1);
    }
    app.use(express.static(dist, { index: false, maxAge: '1h' }));
    app.use((req, res, next) => {
      if (req.method !== 'GET' || req.path.startsWith('/api/')) return next();
      res.sendFile(path.join(dist, 'index.html'));
    });
    log('[server] serving built frontend from dist/');
  }

  await store.init();

  httpServer.listen(config.port, '127.0.0.1', () => {
    log(`[server] http://127.0.0.1:${config.port}`);
  });
}

start().catch((err) => {
  logError('[server] failed to start:', err?.stack || err);
  process.exit(1);
});
