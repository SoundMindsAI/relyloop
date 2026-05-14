'use client';

import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { GuideMetadata } from './guide-types';

export interface GuideViewerProps {
  guideId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface GuideState {
  status: 'loading' | 'loaded' | 'error';
  metadata: GuideMetadata | null;
  error: string | null;
}

/**
 * Walkthrough slideshow rendered as a Radix Dialog. Fetches the guide's
 * metadata.json from `/guides/<id>/metadata.json` (served by Next.js from
 * `ui/public/guides/`), then renders one slide at a time with prev/next
 * controls + arrow-key navigation.
 *
 * Intentionally simpler than the creator-discovery-outreach `<GuideLightbox>`:
 *  - centered modal, not draggable/resizable
 *  - no localStorage persistence of position/size
 *  - no fit-to-viewport toggle
 *
 * Those affordances live behind a feature flag in CDO because the product is
 * mid-flow heavy (users want the guide overlaid while clicking through). For
 * RelyLoop's documentation-first use case, a centered modal is enough.
 */
export function GuideViewer({ guideId, open, onOpenChange }: GuideViewerProps) {
  const [state, setState] = useState<GuideState>({
    status: 'loading',
    metadata: null,
    error: null,
  });
  const [slideIndex, setSlideIndex] = useState(0);

  // React's canonical "reset state when a prop changes" pattern — see
  // https://react.dev/reference/react/useState#storing-information-from-previous-renders
  // The alternative (synchronous setState inside useEffect) trips the
  // react-hooks/incompatible-library "cascading renders" lint rule.
  const [storedGuideId, setStoredGuideId] = useState(guideId);
  if (storedGuideId !== guideId) {
    setStoredGuideId(guideId);
    setState({ status: 'loading', metadata: null, error: null });
    setSlideIndex(0);
  }

  useEffect(() => {
    if (!open) return;
    let cancelled = false;

    async function loadGuide() {
      try {
        const resp = await fetch(`/guides/${guideId}/metadata.json`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const metadata = (await resp.json()) as GuideMetadata;
        if (cancelled) return;
        setState({ status: 'loaded', metadata, error: null });
      } catch (err: unknown) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : String(err);
        setState({ status: 'error', metadata: null, error: message });
      }
    }

    void loadGuide();
    return () => {
      cancelled = true;
    };
  }, [open, guideId]);

  const slides = state.metadata?.screenshots ?? [];
  const slide = slides[slideIndex];
  const total = slides.length;

  useEffect(() => {
    if (!open || total === 0) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') setSlideIndex((i) => Math.min(i + 1, total - 1));
      if (e.key === 'ArrowLeft') setSlideIndex((i) => Math.max(i - 1, 0));
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, total]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-4xl"
        data-testid="guide-viewer"
        aria-label={state.metadata?.title ?? 'Guide'}
      >
        <DialogHeader>
          <DialogTitle data-testid="guide-title">
            {state.status === 'loaded' ? state.metadata?.title : 'Loading…'}
          </DialogTitle>
          <DialogDescription>
            {state.status === 'loaded'
              ? (state.metadata?.description ?? '')
              : 'Loading walkthrough screenshots…'}
          </DialogDescription>
        </DialogHeader>

        {state.status === 'loading' && (
          <p className="py-12 text-center text-sm text-muted-foreground">Loading guide…</p>
        )}

        {state.status === 'error' && (
          <p className="py-12 text-center text-sm text-destructive" data-testid="guide-error">
            Could not load guide: {state.error}
          </p>
        )}

        {state.status === 'loaded' && slide && (
          <div className="space-y-4">
            <div className="overflow-hidden rounded-md border bg-muted">
              {/* Next/Image isn't used here because static `/guides/...` PNGs
                  are served as-is by Next.js. A plain <img> keeps this
                  component flexible and avoids re-encoding the walkthrough
                  artifacts. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/guides/${guideId}/${slide.file}`}
                alt={slide.caption}
                className="block w-full"
                data-testid="guide-slide-image"
              />
            </div>
            <p className="text-sm" data-testid="guide-slide-caption">
              {slide.caption}
            </p>
            <div className="flex items-center justify-between border-t pt-4">
              <Button
                variant="outline"
                disabled={slideIndex === 0}
                onClick={() => setSlideIndex((i) => Math.max(i - 1, 0))}
                data-testid="guide-prev"
              >
                Previous
              </Button>
              <span className="text-xs text-muted-foreground" data-testid="guide-counter">
                {slideIndex + 1} / {total}
              </span>
              <Button
                variant="outline"
                disabled={slideIndex === total - 1}
                onClick={() => setSlideIndex((i) => Math.min(i + 1, total - 1))}
                data-testid="guide-next"
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
