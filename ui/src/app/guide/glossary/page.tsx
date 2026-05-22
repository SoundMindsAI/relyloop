'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';

import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { glossary, type GlossaryEntry } from '@/lib/glossary';
import { cn } from '@/lib/utils';

interface GlossaryRow {
  key: string;
  category: string;
  short?: string;
  long?: string;
}

function entryToRow(key: string, entry: GlossaryEntry): GlossaryRow {
  const category = key.split('.')[0] ?? key;
  const short = 'short' in entry ? entry.short : undefined;
  const long = 'long' in entry ? entry.long : undefined;
  return { key, category, short, long };
}

const ALL_ROWS: readonly GlossaryRow[] = Object.entries(glossary).map(([key, entry]) =>
  entryToRow(key, entry as GlossaryEntry),
);

const ALL_CATEGORIES: readonly string[] = Array.from(
  new Set(ALL_ROWS.map((r) => r.category)),
).sort();

function categoryCount(category: string): number {
  return ALL_ROWS.filter((r) => r.category === category).length;
}

function matchesSearch(row: GlossaryRow, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  if (row.key.toLowerCase().includes(q)) return true;
  if (row.short && row.short.toLowerCase().includes(q)) return true;
  if (row.long && row.long.toLowerCase().includes(q)) return true;
  return false;
}

function matchesFacets(row: GlossaryRow, selected: ReadonlySet<string>): boolean {
  if (selected.size === 0) return true;
  return selected.has(row.category);
}

export default function GlossaryPage() {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<string>>(() => new Set());

  // On initial mount, if a URL fragment is present, re-trigger the
  // native fragment scroll after React has had a tick to render the list.
  // The browser's initial scroll attempt may run before the entry is in
  // the DOM, so we re-fire it in a rAF callback once paint is ready.
  //
  // Filter state is already at defaults (empty query, empty selected) on
  // initial mount, so the anchored entry is always visible — no setState
  // needed. (Hash-change while mounted via in-app navigation is a rare
  // edge case; operators can clear filters manually or hard-refresh.)
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!window.location.hash) return;
    const id = decodeURIComponent(window.location.hash.slice(1));
    requestAnimationFrame(() => {
      const el = document.getElementById(id);
      if (el) el.scrollIntoView({ block: 'start' });
    });
  }, []);

  const filtered = useMemo(
    () => ALL_ROWS.filter((r) => matchesSearch(r, query) && matchesFacets(r, selected)),
    [query, selected],
  );

  const grouped = useMemo(() => {
    const map = new Map<string, GlossaryRow[]>();
    for (const cat of ALL_CATEGORIES) map.set(cat, []);
    for (const row of filtered) {
      const arr = map.get(row.category);
      if (arr) arr.push(row);
    }
    return Array.from(map.entries()).filter(([, rows]) => rows.length > 0);
  }, [filtered]);

  const isSearching = query.trim().length > 0;
  const totalCount = ALL_ROWS.length;

  function toggleCategory(cat: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }

  return (
    <main className="min-h-screen" data-testid="glossary-page">
      <div className="border-b bg-muted/30">
        <div className="mx-auto max-w-5xl px-4 py-3 sm:px-6">
          <Link
            href="/guide"
            className="text-sm text-blue-600 underline-offset-4 hover:underline"
            data-testid="back-to-guides"
          >
            ← All guides
          </Link>
        </div>
      </div>

      <div className="mx-auto max-w-5xl space-y-6 px-4 py-8 sm:px-6">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Glossary</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Every term defined. Search by name or browse by category. Each entry is also
            deep-linkable — append <code className="rounded bg-muted px-1 py-0.5">#term.key</code>{' '}
            to this URL to jump straight to an entry.
          </p>
        </header>

        <div className="space-y-3">
          <div className="max-w-md">
            <Input
              type="search"
              aria-label="Search glossary"
              placeholder={`Search ${totalCount} terms…`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              data-testid="glossary-search"
            />
          </div>

          <div className="flex flex-wrap gap-2" data-testid="glossary-category-chips">
            {ALL_CATEGORIES.map((cat) => {
              const active = selected.has(cat);
              return (
                <button
                  key={cat}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleCategory(cat)}
                  data-testid={`glossary-chip-${cat}`}
                  className={cn(
                    'inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    active
                      ? 'border-blue-600 bg-blue-100 text-blue-900'
                      : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50',
                  )}
                >
                  <code className="font-mono">{cat}</code>
                  <span className="text-muted-foreground">({categoryCount(cat)})</span>
                </button>
              );
            })}
          </div>
        </div>

        {filtered.length === 0 ? (
          <div
            className="rounded-md border border-dashed py-12 text-center"
            data-testid="glossary-empty"
          >
            <p className="text-base font-medium">No terms match.</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Try fewer characters or clear the category filters.
            </p>
          </div>
        ) : isSearching ? (
          <ol className="space-y-4" data-testid="glossary-flat-list">
            {filtered.map((row) => (
              <GlossaryEntryCard key={row.key} row={row} />
            ))}
          </ol>
        ) : (
          <div className="space-y-10" data-testid="glossary-grouped-list">
            {grouped.map(([cat, rows]) => (
              <section
                key={cat}
                aria-labelledby={`glossary-section-${cat}`}
                data-testid={`glossary-section-${cat}`}
              >
                <h2
                  id={`glossary-section-${cat}`}
                  className="mb-3 border-b pb-1 text-lg font-semibold tracking-tight"
                >
                  <code className="font-mono">{cat}</code>
                  <span className="ml-2 text-sm font-normal text-muted-foreground">
                    {rows.length} {rows.length === 1 ? 'term' : 'terms'}
                  </span>
                </h2>
                <ol className="space-y-4">
                  {rows.map((row) => (
                    <GlossaryEntryCard key={row.key} row={row} />
                  ))}
                </ol>
              </section>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

function GlossaryEntryCard({ row }: { row: GlossaryRow }) {
  return (
    <li
      id={row.key}
      data-testid={`glossary-entry-${row.key}`}
      className="rounded-md border border-gray-200 bg-white p-4 shadow-sm scroll-mt-24"
    >
      <h3 className="mb-2 text-base font-semibold">
        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">{row.key}</code>
      </h3>
      {row.short ? <p className="text-sm text-gray-700">{row.short}</p> : null}
      {row.long ? (
        <div
          className={cn('prose prose-sm mt-2 max-w-none text-sm', row.short && 'border-t pt-2')}
          data-testid={`glossary-entry-${row.key}-long`}
        >
          <ReactMarkdown disallowedElements={['script', 'iframe', 'style']} unwrapDisallowed>
            {row.long}
          </ReactMarkdown>
        </div>
      ) : null}
    </li>
  );
}
