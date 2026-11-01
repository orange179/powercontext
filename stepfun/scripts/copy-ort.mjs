import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DIST = path.join(ROOT, 'node_modules', 'onnxruntime-web', 'dist');
const OUT = path.join(ROOT, 'public', 'ort');
const FILES = [
  'ort-wasm-simd-threaded.jsep.wasm',
  'ort-wasm-simd-threaded.jsep.mjs',
  'ort-wasm-simd-threaded.wasm',
  'ort-wasm-simd-threaded.mjs',
];

if (!fs.existsSync(DIST)) {
  console.error(`[ort] onnxruntime-web dist not found at ${DIST}. Run npm install first.`);
  process.exit(1);
}
fs.mkdirSync(OUT, { recursive: true });
let copied = 0;
for (const file of FILES) {
  const src = path.join(DIST, file);
  const dest = path.join(OUT, file);
  if (!fs.existsSync(src)) {
    console.warn(`[ort] missing ${file}, skipped`);
    continue;
  }
  if (fs.existsSync(dest) && fs.statSync(dest).size === fs.statSync(src).size) {
    continue;
  }
  fs.copyFileSync(src, dest);
  copied += 1;
}
console.log(`[ort] wasm runtime assets ready in public/ort (${copied} file(s) updated)`);
