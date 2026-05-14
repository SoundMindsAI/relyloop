'use client';
import { useState } from 'react';

import { GuideViewer } from '@/components/guides/guide-viewer';
import { GUIDE_REGISTRY } from '@/components/guides/guide-types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export default function GuideCatalogPage() {
  const [activeGuideId, setActiveGuideId] = useState<string | null>(null);

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Walkthrough guides</h1>
        <p className="text-sm text-muted-foreground">
          Click a guide to open a step-by-step walkthrough with annotated screenshots.
        </p>
      </div>

      <section
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        data-testid="guide-catalog-grid"
      >
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
