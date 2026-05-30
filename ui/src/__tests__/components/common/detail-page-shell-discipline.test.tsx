// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Discipline lint guard for detail page scaffolding
 * (chore_detail_page_shell_primitive Q3 — regex-based per recommended default).
 *
 * Sibling to `data-table-column-discipline.test.tsx` and
 * `form-select-discipline.test.tsx`. Those scan column configs / form
 * components for source-of-truth violations; this one scans the six
 * `/{entity}/[id]/page.tsx` detail routes for hand-rolled
 * `isPending → isError → data` scaffolds that should use the shared
 * `<DetailPageShell>` primitive instead.
 *
 * Failure mode it catches:
 *   {query.isPending ? (
 *     <Card><CardContent>Loading…</CardContent></Card>
 *   ) : query.isError ? (
 *     <EmptyState title="X not found" message="..." />
 *   ) : query.data ? (
 *     <>{actual content}</>
 *   ) : null}
 *
 * Approved replacement:
 *   <DetailPageShell query={query} entityLabel="..." notFoundErrorCode="..._NOT_FOUND">
 *     {(data) => (
 *       <>{actual content}</>
 *     )}
 *   </DetailPageShell>
 *
 * Escape hatch (per Q3 spec): inline comment with a non-empty reason.
 *   // detail-page-shell-allow: chat surface uses stream-rendered conversation, not a card shell
 *
 * Scope:
 *   - Scans `src/app/<entity>/[id]/page.tsx` files.
 *   - Skips `chat/[id]/page.tsx` (intentionally different scaffold).
 *   - Files that already import `DetailPageShell` are exempt from the
 *     ternary check (any residual `isPending`/`isError` ternaries in
 *     the file refer to subordinate queries — e.g. trials list inside
 *     the migrated study-detail shell — which are correct as-is).
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { basename, join } from 'node:path';

import { describe, expect, it } from 'vitest';

const APP_ROOT = join(process.cwd(), 'src', 'app');

const DETAIL_SHELL_IMPORT_RE =
  /import\s+(?:type\s+)?\{[^}]*\bDetailPageShell\b[^}]*\}\s+from\s+['"]@\/components\/common\/detail-page-shell['"]/;
const IS_PENDING_TERNARY_RE = /\bisPending\s*\?/;
const IS_ERROR_TERNARY_RE = /\bisError\s*\?/;
const ESCAPE_HATCH_RE = /\/\/\s*detail-page-shell-allow:(.*)$/m;

const EXCLUDED_FOLDERS = new Set(['chat']);

interface ValidationError {
  file: string;
  message: string;
}

/**
 * Walk `src/app/` and return every `[id]/page.tsx` file. Detail routes
 * are identified by their parent folder name (`[id]`) rather than a
 * glob — keeps the lint resilient to deeper nesting.
 */
function walkDetailPages(dir: string, ancestors: readonly string[] = []): string[] {
  const out: string[] = [];
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return out;
  }
  for (const name of entries) {
    const full = join(dir, name);
    const stats = statSync(full);
    if (stats.isDirectory()) {
      if (name === '[id]') {
        // The entity folder is the LAST element of `ancestors`. If it's in
        // the excluded set, skip this whole `[id]` subtree.
        const entityFolder = ancestors[ancestors.length - 1];
        if (entityFolder && EXCLUDED_FOLDERS.has(entityFolder)) continue;
        const pagePath = join(full, 'page.tsx');
        try {
          const ps = statSync(pagePath);
          if (ps.isFile()) out.push(pagePath);
        } catch {
          /* no page.tsx in this [id] folder */
        }
      } else {
        out.push(...walkDetailPages(full, [...ancestors, name]));
      }
    }
  }
  return out;
}

/**
 * Returns null when the file is clean (uses DetailPageShell, or doesn't
 * have the offending ternary pattern, or has the escape-hatch comment).
 * Returns a string describing the violation otherwise.
 */
function checkDetailPage(path: string, content: string): string | null {
  if (DETAIL_SHELL_IMPORT_RE.test(content)) return null;

  const hasPendingTernary = IS_PENDING_TERNARY_RE.test(content);
  const hasErrorTernary = IS_ERROR_TERNARY_RE.test(content);
  if (!hasPendingTernary || !hasErrorTernary) return null;

  const hatch = content.match(ESCAPE_HATCH_RE);
  if (hatch) {
    const reason = hatch[1]?.trim();
    if (!reason) {
      return (
        'detail-page-shell-allow escape-hatch comment must include a non-empty reason ' +
        '(e.g. `// detail-page-shell-allow: chat surface uses stream-rendered conversation`)'
      );
    }
    return null;
  }

  return (
    `hand-rolled isPending/isError ternary pattern detected without importing ` +
    `<DetailPageShell> from '@/components/common/detail-page-shell'. ` +
    `Use the shared primitive instead, or add an escape-hatch comment ` +
    `\`// detail-page-shell-allow: <reason>\` if this page is intentionally different.`
  );
}

describe('detail-page-shell discipline lint guard', () => {
  it('every /<entity>/[id]/page.tsx uses <DetailPageShell> (or has an escape hatch)', () => {
    const files = walkDetailPages(APP_ROOT);
    expect(files.length).toBeGreaterThan(0); // sanity — make sure we're actually finding pages

    const errors: ValidationError[] = [];
    for (const file of files) {
      const content = readFileSync(file, 'utf-8');
      const violation = checkDetailPage(file, content);
      if (violation) errors.push({ file, message: violation });
    }

    if (errors.length > 0) {
      const lines = errors.map((e) => `  ${e.file}\n    ${e.message}`);
      throw new Error(
        `${errors.length} detail page(s) failed the discipline check:\n${lines.join('\n')}`,
      );
    }
  });

  it('the chat detail route is intentionally excluded from scanning', () => {
    const chatPage = join(APP_ROOT, 'chat', '[id]', 'page.tsx');
    try {
      statSync(chatPage);
    } catch {
      // If chat/[id]/page.tsx doesn't exist, the exclusion is moot — no test
      // failure. The exclusion list is intent-driven, not file-existence-driven.
      return;
    }
    const files = walkDetailPages(APP_ROOT);
    expect(files.map((p) => basename(p))).toContain('page.tsx');
    expect(files).not.toContain(chatPage);
  });

  it('detects a hand-rolled ternary in a synthetic page', () => {
    const synthetic = `'use client';
import { useFoo } from '@/lib/api/foo';
export default function FooDetailPage() {
  const query = useFoo();
  return query.isPending ? <div>Loading…</div> : query.isError ? <div>Not found</div> : <div>{query.data?.name}</div>;
}
`;
    expect(checkDetailPage('synthetic.tsx', synthetic)).toMatch(/hand-rolled isPending\/isError/);
  });

  it('accepts a page that imports DetailPageShell', () => {
    const synthetic = `'use client';
import { DetailPageShell } from '@/components/common/detail-page-shell';
import { useFoo } from '@/lib/api/foo';
export default function FooDetailPage() {
  const query = useFoo();
  return <DetailPageShell query={query} entityLabel="foo" notFoundErrorCode="FOO_NOT_FOUND">{(foo) => <div>{foo.name}</div>}</DetailPageShell>;
}
`;
    expect(checkDetailPage('synthetic.tsx', synthetic)).toBeNull();
  });

  it('accepts a page with a valid escape-hatch comment', () => {
    const synthetic = `'use client';
import { useFoo } from '@/lib/api/foo';
// detail-page-shell-allow: chat surface uses stream-rendered conversation, not a card shell
export default function FooDetailPage() {
  const query = useFoo();
  return query.isPending ? <div>Loading…</div> : query.isError ? <div>x</div> : <div>{query.data?.name}</div>;
}
`;
    expect(checkDetailPage('synthetic.tsx', synthetic)).toBeNull();
  });

  it('rejects an escape-hatch comment with empty reason', () => {
    const synthetic = `'use client';
import { useFoo } from '@/lib/api/foo';
// detail-page-shell-allow:
export default function FooDetailPage() {
  const query = useFoo();
  return query.isPending ? <div>Loading…</div> : query.isError ? <div>x</div> : <div>{query.data?.name}</div>;
}
`;
    expect(checkDetailPage('synthetic.tsx', synthetic)).toMatch(/non-empty reason/);
  });
});
