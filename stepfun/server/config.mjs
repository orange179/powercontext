import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export const config = {
  port: Number(process.env.PORT || 5173),
  dbPath: path.resolve(process.env.SEEKDB_PATH || path.join(ROOT, 'seekdb_data')),
  isDev: process.argv.includes('--dev'),
  dimension: 512,
  defaultCollection: 'kb_default',
  collectionNamePattern: /^[A-Za-z][A-Za-z0-9_]{0,63}$/,
  fulltextAnalyzer: 'ngram2',
};
