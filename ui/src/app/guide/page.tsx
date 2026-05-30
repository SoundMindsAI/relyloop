// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import { useState } from 'react';

import { GuideViewer } from '@/components/guides/guide-viewer';
import { DOC_REGISTRY, GUIDE_REGISTRY } from '@/components/guides/guide-types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { glossary } from '@/lib/glossary';
import { faq } from '@/lib/faq';

const GLOSSARY_ENTRY_COUNT = Object.keys(glossary).length;
const GLOSSARY_CATEGORY_COUNT = new Set(Object.keys(glossary).map((k) => k.split('.')[0])).size;
const FAQ_ENTRY_COUNT = faq.length;
const FAQ_CATEGORY_COUNT = new Set(faq.map((e) => e.category)).size;

export default function GuideCatalogPage() {
  const [activeGuideId, setActiveGuideId] = useState<string | null>(null);

  return (
    <main className="mx-auto max-w-5xl space-y-10 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Guides</h1>
        <p className="text-sm text-muted-foreground">
          Long-form documentation for first-time setup + visual walkthroughs for every UI workflow.
          Pick a card to dive in.
        </p>
      </div>

      <section className="space-y-3" data-testid="doc-section">
        <header>
          <h2 className="text-lg font-semibold tracking-tight">Tours &amp; tutorials</h2>
          <p className="text-sm text-muted-foreground">
            Big-picture journeys through RelyLoop — pick a 10-minute click-through tour, the full
            30-minute hands-on tutorial, or a workflow inventory.
          </p>
        </header>
        <div className="grid gap-4 sm:grid-cols-2" data-testid="doc-catalog-grid">
          {DOC_REGISTRY.map((doc) => (
            <Link
              key={doc.slug}
              href={`/guide/docs/${doc.slug}`}
              className="block transition hover:opacity-90"
              data-testid={`doc-card-${doc.slug}`}
            >
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">{doc.title}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <p className="text-sm text-muted-foreground">{doc.description}</p>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">
                    {doc.estimatedTime}
                  </p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      </section>

      <section className="space-y-3" data-testid="walkthrough-section">
        <header>
          <h2 className="text-lg font-semibold tracking-tight">Per-workflow walkthroughs</h2>
          <p className="text-sm text-muted-foreground">
            Bite-sized screenshot decks with captions, one per UI workflow. Each opens in a modal
            with fullscreen + larger-text accessibility controls.
          </p>
        </header>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="guide-catalog-grid">
          {GUIDE_REGISTRY.map((guide) => (
            <button
              key={guide.id}
              type="button"
              className="text-left transition hover:opacity-90"
              onClick={() => setActiveGuideId(guide.id)}
              data-testid={`guide-card-${guide.id}`}
            >
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">{guide.title}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <p className="text-sm text-muted-foreground">{guide.description}</p>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">
                    {guide.estimatedTime}
                  </p>
                </CardContent>
              </Card>
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-3" data-testid="reference-section">
        <header>
          <h2 className="text-lg font-semibold tracking-tight">Reference</h2>
          <p className="text-sm text-muted-foreground">
            Browse the canonical terminology and operator-judgment Q&amp;A.
          </p>
        </header>
        <div className="grid gap-4 sm:grid-cols-2" data-testid="reference-catalog-grid">
          <Link
            href="/guide/glossary"
            className="block transition hover:opacity-90"
            data-testid="glossary-card"
          >
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Glossary — every term defined</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  {GLOSSARY_ENTRY_COUNT} terms across {GLOSSARY_CATEGORY_COUNT} categories — search,
                  facet, and deep-link straight to any entry.
                </p>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Reference</p>
              </CardContent>
            </Card>
          </Link>
          <Link
            href="/guide/faq"
            className="block transition hover:opacity-90"
            data-testid="faq-card"
          >
            <Card>
              <CardHeader>
                <CardTitle className="text-base">FAQ — operator-judgment Q&amp;A</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  {FAQ_ENTRY_COUNT} questions across {FAQ_CATEGORY_COUNT} categories — answers
                  shaped for "should I…" / "why is…" / "when does…" questions tooltips can&apos;t
                  carry.
                </p>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Reference</p>
              </CardContent>
            </Card>
          </Link>
        </div>
      </section>

      {activeGuideId && (
        <GuideViewer
          guideId={activeGuideId}
          open={activeGuideId !== null}
          onOpenChange={(open) => {
            if (!open) setActiveGuideId(null);
          }}
        />
      )}
    </main>
  );
}
