'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';

import { Input } from '@/components/ui/input';
import { faq, FAQ_CATEGORIES, FAQ_CATEGORY_ORDER, type FAQCategory } from '@/lib/faq';
import { MARKDOWN_DISALLOWED_ELEMENTS } from '@/lib/markdown-safety';
import { cn } from '@/lib/utils';

function matchesSearch(
  entry: { question: string; answer: string; anchor: string },
  query: string,
): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    entry.question.toLowerCase().includes(q) ||
    entry.answer.toLowerCase().includes(q) ||
    entry.anchor.toLowerCase().includes(q)
  );
}

function matchesFacets(
  entry: { category: FAQCategory },
  selected: ReadonlySet<FAQCategory>,
): boolean {
  if (selected.size === 0) return true;
  return selected.has(entry.category);
}

export default function FAQPage() {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<FAQCategory>>(() => new Set());

  // Native fragment scroll re-fire after React paints (FAQ uses deep links the
  // same way glossary does — see `app/guide/glossary/page.tsx` for the rationale).
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
    () => faq.filter((e) => matchesSearch(e, query) && matchesFacets(e, selected)),
    [query, selected],
  );

  const byCategory = useMemo(() => {
    const map = new Map<FAQCategory, (typeof faq)[number][]>();
    for (const cat of FAQ_CATEGORY_ORDER) map.set(cat, []);
    for (const entry of filtered) {
      const arr = map.get(entry.category);
      if (arr) arr.push(entry);
    }
    return FAQ_CATEGORY_ORDER.filter((c) => (map.get(c)?.length ?? 0) > 0).map(
      (c) => [c, map.get(c) ?? []] as const,
    );
  }, [filtered]);

  const isSearching = query.trim().length > 0;

  function toggleCategory(cat: FAQCategory) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }

  function categoryCount(cat: FAQCategory): number {
    return faq.filter((e) => e.category === cat).length;
  }

  return (
    <main className="min-h-screen" data-testid="faq-page">
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
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Frequently asked questions
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Operator-judgment-shaped Q&amp;A — "should I…", "why is…", "when does…". For term
            definitions, see the{' '}
            <Link
              href="/guide/glossary"
              className="text-blue-600 underline-offset-4 hover:underline"
            >
              glossary
            </Link>
            . Each FAQ entry is deep-linkable — append{' '}
            <code className="rounded bg-muted px-1 py-0.5">#anchor-name</code> to this URL.
          </p>
        </header>

        <div className="space-y-3">
          <div className="max-w-md">
            <Input
              type="search"
              aria-label="Search FAQ"
              placeholder={`Search ${faq.length} questions…`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              data-testid="faq-search"
            />
          </div>

          <div className="flex flex-wrap gap-2" data-testid="faq-category-chips">
            {FAQ_CATEGORY_ORDER.map((cat) => {
              const active = selected.has(cat);
              return (
                <button
                  key={cat}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleCategory(cat)}
                  data-testid={`faq-chip-${cat}`}
                  className={cn(
                    'inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    active
                      ? 'border-blue-600 bg-blue-100 text-blue-900'
                      : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50',
                  )}
                >
                  <span>{FAQ_CATEGORIES[cat]}</span>
                  <span className="text-muted-foreground">({categoryCount(cat)})</span>
                </button>
              );
            })}
          </div>
        </div>

        {filtered.length === 0 ? (
          <div
            className="rounded-md border border-dashed py-12 text-center"
            data-testid="faq-empty"
          >
            <p className="text-base font-medium">No questions match.</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Try fewer characters or clear the category filters.
            </p>
          </div>
        ) : isSearching ? (
          <ol className="space-y-6" data-testid="faq-flat-list">
            {filtered.map((entry) => (
              <FAQEntryCard key={entry.anchor} entry={entry} />
            ))}
          </ol>
        ) : (
          <div className="space-y-10" data-testid="faq-grouped-list">
            {byCategory.map(([cat, entries]) => (
              <section
                key={cat}
                aria-labelledby={`faq-section-${cat}`}
                data-testid={`faq-section-${cat}`}
              >
                <h2
                  id={`faq-section-${cat}`}
                  className="mb-3 border-b pb-1 text-lg font-semibold tracking-tight"
                >
                  {FAQ_CATEGORIES[cat]}
                  <span className="ml-2 text-sm font-normal text-muted-foreground">
                    {entries.length} {entries.length === 1 ? 'question' : 'questions'}
                  </span>
                </h2>
                <ol className="space-y-6">
                  {entries.map((entry) => (
                    <FAQEntryCard key={entry.anchor} entry={entry} />
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

function FAQEntryCard({ entry }: { entry: (typeof faq)[number] }) {
  return (
    <li
      id={entry.anchor}
      data-testid={`faq-entry-${entry.anchor}`}
      className="rounded-md border border-gray-200 bg-white p-4 shadow-sm scroll-mt-24"
    >
      <h3 className="mb-2 text-base font-semibold">
        <a
          href={`#${entry.anchor}`}
          className="text-foreground hover:text-blue-700"
          data-testid={`faq-anchor-${entry.anchor}`}
        >
          {entry.question}
        </a>
      </h3>
      <div className="prose prose-sm max-w-none text-sm" data-testid={`faq-answer-${entry.anchor}`}>
        <ReactMarkdown disallowedElements={[...MARKDOWN_DISALLOWED_ELEMENTS]} unwrapDisallowed>
          {entry.answer}
        </ReactMarkdown>
      </div>
    </li>
  );
}
