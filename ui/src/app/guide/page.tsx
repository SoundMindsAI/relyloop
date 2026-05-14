'use client';
import Link from 'next/link';
import { useState } from 'react';

import { GuideViewer } from '@/components/guides/guide-viewer';
import { DOC_REGISTRY, GUIDE_REGISTRY } from '@/components/guides/guide-types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

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
          <h2 className="text-lg font-semibold tracking-tight">Long-form documentation</h2>
          <p className="text-sm text-muted-foreground">
            In-depth reading for setting up RelyLoop end-to-end + understanding the full capability
            surface.
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
          <h2 className="text-lg font-semibold tracking-tight">Visual walkthroughs</h2>
          <p className="text-sm text-muted-foreground">
            Step-by-step screenshot decks with captions. Each walkthrough opens in a modal with
            fullscreen + larger-text accessibility controls.
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
