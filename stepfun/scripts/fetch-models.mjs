#!/usr/bin/env node
/**
 * Download the pinned bge-small-zh-v1.5 ONNX export used by the app.
 *
 * Model: Xenova/bge-small-zh-v1.5 (ONNX export of BAAI/bge-small-zh-v1.5, 512-dim Chinese embedding model)
 * Revision: 75c43b069aac4d136ba6bc1122f995fedcfd2781
 * Source: https://huggingface.co/Xenova/bge-small-zh-v1.5 (mirror: hf-mirror.com)
 *
 * Usage:
 *   node scripts/fetch-models.mjs            # fp16 + int8 (runtime files)
 *   node scripts/fetch-models.mjs --all      # + fp32 (quality baseline)
 *   node scripts/fetch-models.mjs --force    # re-download existing files
 */
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const MODEL_ID = 'Xenova/bge-small-zh-v1.5';
const REVISION = '75c43b069aac4d136ba6bc1122f995fedcfd2781';
const BASE = process.env.MODEL_BASE_URL || 'https://hf-mirror.com';
const OUT_DIR = path.join(ROOT, 'public', 'models', MODEL_ID);

const COMMON_FILES = [
  'config.json',
  'tokenizer.json',
  'tokenizer_config.json',
  'special_tokens_map.json',
  'vocab.txt',
  'quantize_config.json',
];

const ONNX_FILES = {
  fp32: 'onnx/model.onnx',
  fp16: 'onnx/model_fp16.onnx',
  int8: 'onnx/model_int8.onnx',
};

// Exact sizes for the pinned revision, verified against the local manifest after download.
const EXPECTED_BYTES = {
  [ONNX_FILES.fp32]: 94851877,
  [ONNX_FILES.fp16]: 47497427,
  [ONNX_FILES.int8]: 23903394,
};

const args = new Set(process.argv.slice(2));
const includeFp32 = args.has('--all');
const force = args.has('--force');
const files = [...COMMON_FILES, ONNX_FILES.fp16, ONNX_FILES.int8, ...(includeFp32 ? [ONNX_FILES.fp32] : [])];

const sha256 = (buf) => createHash('sha256').update(buf).digest('hex');

async function download(rel) {
  const url = `${BASE}/${MODEL_ID}/resolve/${REVISION}/${rel}?download=true`;
  const dest = path.join(OUT_DIR, rel);
  await fsp.mkdir(path.dirname(dest), { recursive: true });

  if (!force && fs.existsSync(dest) && fs.statSync(dest).size > 0) {
    console.log(`[skip] ${rel} (${(fs.statSync(dest).size / 1048576).toFixed(2)} MiB already present)`);
    return { file: rel, bytes: fs.statSync(dest).size };
  }

  const started = Date.now();
  for (let attempt = 1; ; attempt += 1) {
    const res = await fetch(url, { redirect: 'follow' });
    if (!res.ok) throw new Error(`${rel}: HTTP ${res.status}`);
    const tmp = `${dest}.part`;
    const out = fs.createWriteStream(tmp);
    let received = 0;
    let lastPrint = 0;
    for await (const chunk of res.body) {
      received += chunk.length;
      if (!out.write(chunk)) await new Promise((r) => out.once('drain', r));
      const now = Date.now();
      if (now - lastPrint > 2000) {
        lastPrint = now;
        process.stdout.write(`\r[get ] ${rel} ${(received / 1048576).toFixed(1)} MiB`);
      }
    }
    await new Promise((resolve, reject) => out.end((err) => (err ? reject(err) : resolve())));
    process.stdout.write('\n');

    const expected = EXPECTED_BYTES[rel];
    if (!expected || received === expected) {
      await fsp.rename(tmp, dest);
      console.log(`[done] ${rel} ${(received / 1048576).toFixed(2)} MiB in ${((Date.now() - started) / 1000).toFixed(1)}s`);
      return { file: rel, bytes: received };
    }
    await fsp.rm(tmp, { force: true });
    if (attempt >= 3) throw new Error(`${rel}: size mismatch (${received}/${expected}) after ${attempt} attempts`);
    console.log(`[retry] ${rel} size mismatch (${received}/${expected}), retrying (${attempt}/3)`);
  }
}

const results = [];
for (const rel of files) results.push(await download(rel));

const manifest = {
  model: MODEL_ID,
  revision: REVISION,
  source: `https://huggingface.co/${MODEL_ID}/tree/${REVISION}`,
  mirror: BASE,
  fetchedAt: new Date().toISOString(),
  files: [],
};
for (const { file, bytes } of results) {
  const full = path.join(OUT_DIR, file);
  manifest.files.push({ file, bytes, sha256: sha256(await fsp.readFile(full)) });
}
await fsp.writeFile(path.join(OUT_DIR, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');

const byName = Object.fromEntries(manifest.files.map((f) => [f.file, f.bytes]));
const fp32 = byName[ONNX_FILES.fp32];
const fp16 = byName[ONNX_FILES.fp16];
const int8 = byName[ONNX_FILES.int8];
console.log('\nONNX model sizes');
if (fp32) console.log(`  fp32 ${(fp32 / 1048576).toFixed(2)} MiB`);
if (fp16) console.log(`  fp16 ${(fp16 / 1048576).toFixed(2)} MiB${fp32 ? `  compression ${(fp32 / fp16).toFixed(2)}x` : ''}`);
if (int8) console.log(`  int8 ${(int8 / 1048576).toFixed(2)} MiB${fp32 ? `  compression ${(fp32 / int8).toFixed(2)}x` : ''}`);
console.log(`\nManifest written to ${path.relative(ROOT, path.join(OUT_DIR, 'manifest.json'))}`);
