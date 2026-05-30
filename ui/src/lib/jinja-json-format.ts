// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Pretty-print a Jinja2-flavored JSON template body.
 *
 * Real RelyLoop templates mix Jinja expressions in two positions:
 *  - Inside a JSON string: `"query": "{{ query_text }}"` or
 *    `"title^{{ title_boost }}"` — these are already valid JSON.
 *  - Outside a JSON string (numeric/boolean position): `"boost": {{ boost }}`
 *    — these would fail `JSON.parse`.
 *
 * Strategy:
 *  1. Walk the source character-by-character, tracking JSON string context.
 *  2. Replace each Jinja expression in an UNQUOTED position with a unique
 *     quoted sentinel `"__JINJA_PLACEHOLDER_N__"`. Jinja expressions inside
 *     JSON strings are left alone (they're valid JSON already).
 *  3. `JSON.parse` the sentinelled text, then `JSON.stringify(_, null, 2)`.
 *  4. Replace each `"__JINJA_PLACEHOLDER_N__"` (with surrounding quotes)
 *     back to the original `{{ ... }}` expression — this strips the
 *     sentinel's quotes so the output matches the source's unquoted form.
 */

const SENTINEL_PREFIX = '__JINJA_PLACEHOLDER_';
const SENTINEL_SUFFIX = '__';

export type PrettyPrintResult = { ok: true; text: string } | { ok: false; error: string };

export function prettyPrintJinjaJson(source: string): PrettyPrintResult {
  if (source.trim() === '') {
    return { ok: false, error: 'empty body' };
  }
  const { sentinelled, placeholders } = sentinelUnquotedJinja(source);
  let parsed: unknown;
  try {
    parsed = JSON.parse(sentinelled);
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
  let formatted: string;
  try {
    formatted = JSON.stringify(parsed, null, 2);
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
  for (let i = 0; i < placeholders.length; i += 1) {
    const token = `"${SENTINEL_PREFIX}${i}${SENTINEL_SUFFIX}"`;
    formatted = formatted.split(token).join(placeholders[i]!);
  }
  return { ok: true, text: formatted };
}

function sentinelUnquotedJinja(source: string): {
  sentinelled: string;
  placeholders: string[];
} {
  const out: string[] = [];
  const placeholders: string[] = [];
  let inString = false;
  let escape = false;
  let i = 0;
  while (i < source.length) {
    const ch = source[i]!;
    if (inString) {
      out.push(ch);
      if (escape) {
        escape = false;
      } else if (ch === '\\') {
        escape = true;
      } else if (ch === '"') {
        inString = false;
      }
      i += 1;
      continue;
    }
    if (ch === '"') {
      inString = true;
      out.push(ch);
      i += 1;
      continue;
    }
    if (ch === '{' && source[i + 1] === '{') {
      const end = source.indexOf('}}', i + 2);
      if (end === -1) {
        // Unterminated Jinja — pass through verbatim; JSON.parse will fail
        // and surface a clear error.
        out.push(ch);
        i += 1;
        continue;
      }
      const expr = source.slice(i, end + 2);
      const index = placeholders.length;
      placeholders.push(expr);
      out.push(`"${SENTINEL_PREFIX}${index}${SENTINEL_SUFFIX}"`);
      i = end + 2;
      continue;
    }
    out.push(ch);
    i += 1;
  }
  return { sentinelled: out.join(''), placeholders };
}
