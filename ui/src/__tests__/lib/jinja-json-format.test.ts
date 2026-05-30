// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { prettyPrintJinjaJson } from '@/lib/jinja-json-format';

describe('prettyPrintJinjaJson', () => {
  it('formats a single-line minified template with Jinja in scalar position', () => {
    const source = '{"query":{"match":{"title":{"query":"{{ query_text }}"}}}}';
    const result = prettyPrintJinjaJson(source);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.text).toBe(
        [
          '{',
          '  "query": {',
          '    "match": {',
          '      "title": {',
          '        "query": "{{ query_text }}"',
          '      }',
          '    }',
          '  }',
          '}',
        ].join('\n'),
      );
    }
  });

  it('formats a template with Jinja in unquoted numeric position', () => {
    const source =
      '{ "query": { "match": { "title": { "query": "{{ query_text }}", "boost": {{ boost }} } } } }';
    const result = prettyPrintJinjaJson(source);
    expect(result.ok).toBe(true);
    if (result.ok) {
      // The Jinja in the unquoted "boost" position must render WITHOUT
      // surrounding quotes (matching the source's numeric position).
      expect(result.text).toContain('"boost": {{ boost }}');
      expect(result.text).not.toContain('"boost": "{{');
      // The Jinja inside the string keeps its quotes.
      expect(result.text).toContain('"query": "{{ query_text }}"');
    }
  });

  it('preserves Jinja embedded inside a longer string', () => {
    const source =
      '{"query":{"multi_match":{"query":"{{ query_text }}","fields":["title^{{ title_boost }}","description","brand^2"],"type":"best_fields"}}}';
    const result = prettyPrintJinjaJson(source);
    expect(result.ok).toBe(true);
    if (result.ok) {
      // The whole `title^{{ title_boost }}` lives inside one JSON string —
      // pretty-printing must not split or re-quote it.
      expect(result.text).toContain('"title^{{ title_boost }}"');
      expect(result.text).toContain('"description"');
      expect(result.text).toContain('"brand^2"');
    }
  });

  it('handles multiple Jinja expressions in mixed positions', () => {
    const source =
      '{"query":{"function_score":{"query":{"match":{"title":"{{ q }}"}},"functions":[{"gauss":{"price":{"origin":0,"scale":{{ scale }},"decay":{{ decay }}}}}]}}}';
    const result = prettyPrintJinjaJson(source);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.text).toContain('"title": "{{ q }}"');
      expect(result.text).toContain('"scale": {{ scale }}');
      expect(result.text).toContain('"decay": {{ decay }}');
    }
  });

  it('returns ok=false with the JSON parse error for invalid templates', () => {
    const source = '{"query": {"missing_close":}';
    const result = prettyPrintJinjaJson(source);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toMatch(/JSON|Unexpected|Expected/i);
    }
  });

  it('returns ok=false for an empty body', () => {
    expect(prettyPrintJinjaJson('').ok).toBe(false);
    expect(prettyPrintJinjaJson('   \n  ').ok).toBe(false);
  });

  it('is idempotent — running twice produces the same output', () => {
    const source =
      '{ "query": { "match": { "title": { "query": "{{ q }}", "boost": {{ b }} } } } }';
    const first = prettyPrintJinjaJson(source);
    expect(first.ok).toBe(true);
    if (first.ok) {
      const second = prettyPrintJinjaJson(first.text);
      expect(second.ok).toBe(true);
      if (second.ok) {
        expect(second.text).toBe(first.text);
      }
    }
  });

  it('does not match the leading `{` of `{{` as a JSON object opener', () => {
    // Regression guard: when the body starts with Jinja in an unquoted
    // position (rare but valid), the scanner should NOT mis-step.
    const source = '{ "boost": {{ boost }} }';
    const result = prettyPrintJinjaJson(source);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.text).toBe(['{', '  "boost": {{ boost }}', '}'].join('\n'));
    }
  });

  it('preserves escape sequences inside strings', () => {
    const source = '{"q":"line1\\nline2","b":{{ b }}}';
    const result = prettyPrintJinjaJson(source);
    expect(result.ok).toBe(true);
    if (result.ok) {
      // JSON.stringify re-escapes \n as \\n in the output.
      expect(result.text).toContain('"q": "line1\\nline2"');
      expect(result.text).toContain('"b": {{ b }}');
    }
  });
});
