import type { PreparedDoc, SourceDoc } from './types';

const MAX_CHARS = 520;
const OVERLAP = 80;

export function fnv1a(input: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(36);
}

export function detectLang(text: string): string {
  return /[\u3400-\u9fff]/.test(text) ? 'zh' : 'en';
}

function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[。！？!?；;])\s*|\n+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function splitPassages(text: string, maxChars = MAX_CHARS, overlap = OVERLAP): string[] {
  const normalized = text.replace(/\r\n/g, '\n').trim();
  if (!normalized) return [];
  if (normalized.length <= maxChars) return [normalized];

  const units = normalized
    .split(/\n{2,}/)
    .flatMap((paragraph) => (paragraph.length > maxChars ? splitSentences(paragraph) : [paragraph]))
    .map((s) => s.trim())
    .filter(Boolean);

  const passages: string[] = [];
  let current = '';
  for (const unit of units) {
    if (!current) {
      current = unit;
    } else if (current.length + unit.length + 1 <= maxChars) {
      current = `${current}\n${unit}`;
    } else {
      passages.push(current);
      const tail = current.slice(Math.max(0, current.length - overlap));
      current = tail && unit.length + tail.length + 1 <= maxChars ? `${tail}\n${unit}` : unit;
    }
  }
  if (current) passages.push(current);
  return passages;
}

export function prepareDocuments(
  docs: SourceDoc[],
  options: { source?: string; category?: string; maxChars?: number; overlap?: number } = {},
): PreparedDoc[] {
  const prepared: PreparedDoc[] = [];
  docs.forEach((doc, docIndex) => {
    const source = (doc.source || options.source || 'manual').trim();
    const title = (doc.title || deriveTitle(doc.text) || `文档 ${docIndex + 1}`).trim();
    const category = (doc.category || options.category || '未分类').trim();
    const lang = doc.lang || detectLang(doc.text);
    const passages = splitPassages(doc.text, options.maxChars ?? MAX_CHARS, options.overlap ?? OVERLAP);
    passages.forEach((passage, index) => {
      const baseId = doc.id || `doc-${fnv1a(`${source}|${title}|${passage}`)}`;
      const id = passages.length > 1 ? `${baseId}-c${index + 1}` : baseId;
      prepared.push({
        id,
        text: passage,
        title: passages.length > 1 ? `${title} (${index + 1}/${passages.length})` : title,
        category,
        source,
        lang,
        chunk: index,
        totalChunks: passages.length,
      });
    });
  });
  return prepared;
}

function deriveTitle(text: string): string | null {
  const firstLine = text.split('\n').find((line) => line.trim().length > 0);
  if (!firstLine) return null;
  const cleaned = firstLine.replace(/^#+\s*/, '').trim();
  return cleaned.length > 48 ? `${cleaned.slice(0, 48)}…` : cleaned;
}

export function parseTextInput(text: string, fallbackTitle = '粘贴的文档'): SourceDoc[] {
  const blocks = text
    .replace(/\r\n/g, '\n')
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);
  const docs: SourceDoc[] = [];
  let currentTitle = fallbackTitle;
  let buffer: string[] = [];
  const flush = () => {
    const content = buffer.join('\n\n').trim();
    if (content) docs.push({ text: content, title: currentTitle });
    buffer = [];
  };
  for (const block of blocks) {
    const heading = block.match(/^#{1,3}\s+(.+)$/);
    if (heading) {
      flush();
      currentTitle = heading[1].trim();
    } else {
      buffer.push(block);
    }
  }
  flush();
  return docs.length > 0 ? docs : text.trim() ? [{ text: text.trim(), title: fallbackTitle }] : [];
}

export function parseJsonInput(raw: string): SourceDoc[] {
  const parsed = JSON.parse(raw) as unknown;
  const rows = Array.isArray(parsed)
    ? parsed
    : parsed && typeof parsed === 'object' && Array.isArray((parsed as { documents?: unknown }).documents)
      ? (parsed as { documents: unknown[] }).documents
      : [];
  const docs: SourceDoc[] = [];
  for (const row of rows) {
    if (typeof row === 'string') {
      docs.push({ text: row });
    } else if (row && typeof row === 'object') {
      const item = row as Record<string, unknown>;
      const text = item.text ?? item.content ?? item.document ?? item.body;
      if (typeof text === 'string' && text.trim()) {
        docs.push({
          text,
          id: typeof item.id === 'string' ? item.id : undefined,
          title: typeof item.title === 'string' ? item.title : undefined,
          category: typeof item.category === 'string' ? item.category : undefined,
          source: typeof item.source === 'string' ? item.source : undefined,
          lang: typeof item.lang === 'string' ? item.lang : undefined,
        });
      }
    }
  }
  return docs;
}

export function parseCsvInput(raw: string): SourceDoc[] {
  const rows: string[][] = [];
  let field = '';
  let row: string[] = [];
  let quoted = false;
  for (let i = 0; i < raw.length; i += 1) {
    const ch = raw[i];
    if (quoted) {
      if (ch === '"' && raw[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (ch === '"') {
        quoted = false;
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ',') {
      row.push(field);
      field = '';
    } else if (ch === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else if (ch !== '\r') {
      field += ch;
    }
  }
  row.push(field);
  if (row.some((cell) => cell.length > 0)) rows.push(row);
  if (rows.length === 0) return [];
  const header = rows[0].map((h) => h.trim().toLowerCase());
  const indexOf = (...names: string[]) => {
    for (const name of names) {
      const idx = header.indexOf(name);
      if (idx >= 0) return idx;
    }
    return -1;
  };
  const textIdx = indexOf('text', 'content', 'document', 'body');
  if (textIdx < 0) {
    return rows.map((cells) => ({ text: cells.join(' ') })).filter((d) => d.text.trim());
  }
  const titleIdx = indexOf('title');
  const categoryIdx = indexOf('category');
  const sourceIdx = indexOf('source');
  const idIdx = indexOf('id');
  return rows
    .slice(1)
    .filter((cells) => cells[textIdx]?.trim())
    .map((cells) => ({
      text: cells[textIdx],
      title: titleIdx >= 0 ? cells[titleIdx] : undefined,
      category: categoryIdx >= 0 ? cells[categoryIdx] : undefined,
      source: sourceIdx >= 0 ? cells[sourceIdx] : undefined,
      id: idIdx >= 0 ? cells[idIdx] : undefined,
    }));
}

export function parseFile(name: string, content: string): SourceDoc[] {
  const lower = name.toLowerCase();
  if (lower.endsWith('.json')) return parseJsonInput(content);
  if (lower.endsWith('.csv')) return parseCsvInput(content);
  return parseTextInput(content, name.replace(/\.[^.]+$/, ''));
}
