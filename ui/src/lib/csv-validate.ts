/**
 * UI-side CSV pre-submit guard (spec §10). The backend has its own quota and
 * row-level validators (returns `INVALID_CSV` with row numbers). This helper
 * fails fast on obvious mistakes:
 *
 *   - file size > 10 MB (spec §10 — UI guardrail; backend caps too).
 *   - first row missing the required `query_text` column.
 */

export const QUERY_CSV_MAX_BYTES = 10 * 1024 * 1024;

export interface ValidateCsvOptions {
  /** Allowed header columns. Required: `query_text`. Optional: `doc_id`, `metadata`. */
  allowedHeaders?: readonly string[];
  requiredHeaders?: readonly string[];
}

export interface CsvValidationResult {
  ok: boolean;
  error?: string;
  rowCount?: number;
}

const DEFAULT_ALLOWED = ['query_text', 'reference_answer', 'metadata'] as const;
const DEFAULT_REQUIRED = ['query_text'] as const;

export function validateQueryCsv(
  text: string,
  size: number,
  opts: ValidateCsvOptions = {},
): CsvValidationResult {
  if (size > QUERY_CSV_MAX_BYTES) {
    return {
      ok: false,
      error: `CSV must be ≤ ${(QUERY_CSV_MAX_BYTES / 1024 / 1024).toFixed(0)} MB (got ${(size / 1024 / 1024).toFixed(2)} MB).`,
    };
  }
  const allowed = opts.allowedHeaders ?? DEFAULT_ALLOWED;
  const required = opts.requiredHeaders ?? DEFAULT_REQUIRED;
  const lines = text.split('\n').filter((l) => l.trim().length > 0);
  if (lines.length === 0) {
    return { ok: false, error: 'CSV is empty.' };
  }
  const headerLine = lines[0];
  if (!headerLine) {
    return { ok: false, error: 'CSV is missing a header row.' };
  }
  const headers = headerLine.split(',').map((c) => c.trim());
  for (const req of required) {
    if (!headers.includes(req)) {
      return { ok: false, error: `CSV header must include the column "${req}".` };
    }
  }
  for (const h of headers) {
    if (!allowed.includes(h)) {
      return {
        ok: false,
        error: `Unknown CSV column "${h}". Allowed: ${allowed.join(', ')}.`,
      };
    }
  }
  return { ok: true, rowCount: lines.length - 1 };
}
