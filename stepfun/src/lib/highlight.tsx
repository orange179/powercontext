import type { ReactNode } from 'react';

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export function highlightText(text: string, query: string): ReactNode {
  const trimmed = query.trim();
  if (!trimmed) return text;
  const tokens = new Set<string>([trimmed]);
  for (const token of trimmed.split(/[\s,，。;；:：?？!！、/]+/)) {
    if (token.length >= 2) tokens.add(token);
  }
  const pattern = [...tokens]
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join('|');
  if (!pattern) return text;
  const parts = text.split(new RegExp(`(${pattern})`, 'gi'));
  return parts.map((part, index) =>
    index % 2 === 1 ? (
      <mark key={index} className="hl">
        {part}
      </mark>
    ) : (
      <span key={index}>{part}</span>
    ),
  );
}
