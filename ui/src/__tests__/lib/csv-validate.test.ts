import { describe, expect, it } from 'vitest';

import { validateQueryCsv, QUERY_CSV_MAX_BYTES } from '@/lib/csv-validate';

describe('validateQueryCsv', () => {
  it('accepts a header with just query_text', () => {
    const text = 'query_text\nred shoes\nblue shoes';
    expect(validateQueryCsv(text, text.length)).toEqual({ ok: true, rowCount: 2 });
  });

  it('accepts allowed optional headers', () => {
    const text = 'query_text,reference_answer,metadata\nq1,a1,{"k":"v"}';
    expect(validateQueryCsv(text, text.length).ok).toBe(true);
  });

  it('rejects when query_text is missing', () => {
    const text = 'reference_answer,metadata\nrow';
    expect(validateQueryCsv(text, text.length).ok).toBe(false);
  });

  it('rejects unknown headers', () => {
    const text = 'query_text,doc_id\nq1,d1';
    const r = validateQueryCsv(text, text.length);
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/Unknown CSV column "doc_id"/);
  });

  it('rejects files larger than 10MB', () => {
    const r = validateQueryCsv('query_text\nrow', QUERY_CSV_MAX_BYTES + 1);
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/≤ 10 MB/);
  });

  it('rejects empty CSV', () => {
    expect(validateQueryCsv('', 0).ok).toBe(false);
  });
});
