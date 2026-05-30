// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import * as DialogPrimitive from '@radix-ui/react-dialog';
import { ExternalLink, Maximize2, Minimize2, X } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { DialogOverlay, DialogPortal } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
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

type TextSize = 'sm' | 'base' | 'lg';
const TEXT_SIZE_CYCLE: TextSize[] = ['sm', 'base', 'lg'];

// localStorage keys — namespaced per a `relyloop.<feature>.<key>` convention.
const STORAGE_FULLSCREEN = 'relyloop.guide-viewer.fullscreen';
const STORAGE_TEXT_SIZE = 'relyloop.guide-viewer.text-size';

function readStoredBool(key: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === '1') return true;
    if (raw === '0') return false;
    return fallback;
  } catch {
    return fallback;
  }
}

function readStoredTextSize(): TextSize {
  if (typeof window === 'undefined') return 'base';
  try {
    const raw = window.localStorage.getItem(STORAGE_TEXT_SIZE);
    if (raw === 'sm' || raw === 'base' || raw === 'lg') return raw;
    return 'base';
  } catch {
    return 'base';
  }
}

function writeStored(key: string, value: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // ignore (private browsing / quota)
  }
}

/**
 * Walkthrough slideshow rendered as a Radix Dialog. Fetches the guide's
 * metadata.json from `/guides/<id>/metadata.json` (Next.js serves it from
 * `ui/public/guides/`), then renders one slide at a time.
 *
 * Usability affordances tuned for documentation use, mobile, and low-vision:
 *  - **Responsive sizing.** Default `w-[96vw] max-w-[1100px] h-[92vh]` so the
 *    viewer scales to any viewport from phone to ultrawide.
 *  - **Fullscreen toggle.** Expands the dialog to `w-screen h-screen` —
 *    indispensable when guide screenshots include small UI text. Preference
 *    persists in localStorage so the user's choice carries across sessions.
 *  - **Text-size toggle.** Cycles caption + description through three sizes
 *    (sm / base / lg) for low-vision support. Preference persisted.
 *  - **View full PNG.** Inline link below the image opens the raw screenshot
 *    in a new tab — gives the user the browser's native zoom for any detail
 *    that doesn't fit on screen at the chosen viewer size.
 *  - **Aria-live caption** so screen readers announce slide transitions.
 *  - **Keyboard nav.** Arrow keys for prev/next, Escape for close
 *    (Radix-provided), 'f' toggles fullscreen.
 */
export function GuideViewer({ guideId, open, onOpenChange }: GuideViewerProps) {
  const [state, setState] = useState<GuideState>({
    status: 'loading',
    metadata: null,
    error: null,
  });
  const [slideIndex, setSlideIndex] = useState(0);
  const [fullscreen, setFullscreen] = useState<boolean>(() =>
    readStoredBool(STORAGE_FULLSCREEN, false),
  );
  const [textSize, setTextSize] = useState<TextSize>(() => readStoredTextSize());
  const [mode, setMode] = useState<'slides' | 'video'>('slides');

  // React's canonical "reset state when a prop changes" pattern — see
  // https://react.dev/reference/react/useState#storing-information-from-previous-renders
  const [storedGuideId, setStoredGuideId] = useState(guideId);
  if (storedGuideId !== guideId) {
    setStoredGuideId(guideId);
    setState({ status: 'loading', metadata: null, error: null });
    setSlideIndex(0);
    setMode('slides');
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

  const toggleFullscreen = useCallback(() => {
    setFullscreen((prev) => {
      const next = !prev;
      writeStored(STORAGE_FULLSCREEN, next ? '1' : '0');
      return next;
    });
  }, []);

  const cycleTextSize = useCallback(() => {
    setTextSize((prev) => {
      const idx = TEXT_SIZE_CYCLE.indexOf(prev);
      const next = TEXT_SIZE_CYCLE[(idx + 1) % TEXT_SIZE_CYCLE.length]!;
      writeStored(STORAGE_TEXT_SIZE, next);
      return next;
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      // Don't hijack keys when a form input is focused (Radix Dialog traps
      // focus, so usually the body has focus and these handlers fire — but
      // a future "Take notes" field shouldn't get arrow keys eaten).
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      // Fullscreen is available as soon as the viewer opens — even during
      // metadata load. Slide navigation is gated on `total > 0` because
      // there's nothing to navigate before slides are loaded.
      if (e.key === 'f' || e.key === 'F') toggleFullscreen();
      if (total === 0) return;
      if (e.key === 'ArrowRight') setSlideIndex((i) => Math.min(i + 1, total - 1));
      if (e.key === 'ArrowLeft') setSlideIndex((i) => Math.max(i - 1, 0));
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, total, toggleFullscreen]);

  const captionSizeClass =
    textSize === 'sm' ? 'text-sm' : textSize === 'base' ? 'text-base' : 'text-lg';
  const descSizeClass =
    textSize === 'sm' ? 'text-xs' : textSize === 'base' ? 'text-sm' : 'text-base';

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay />
        <DialogPrimitive.Content
          data-testid="guide-viewer"
          aria-label={state.metadata?.title ?? 'Guide'}
          data-fullscreen={fullscreen ? 'true' : 'false'}
          data-text-size={textSize}
          className={cn(
            'fixed z-50 flex flex-col gap-3 border bg-background shadow-lg outline-none',
            // Responsive sizing. Default = centered, scales to viewport with
            // a sensible cap; fullscreen = edge-to-edge.
            fullscreen
              ? 'inset-0 h-screen w-screen max-w-none rounded-none p-4'
              : 'left-1/2 top-1/2 h-[92vh] max-h-[900px] w-[96vw] max-w-[1100px] -translate-x-1/2 -translate-y-1/2 rounded-lg p-4 sm:p-6',
          )}
        >
          {/* Header: title (left) + controls (right). Stacks on narrow viewports. */}
          <div className="flex items-start justify-between gap-3 border-b pb-3">
            <div className="min-w-0 flex-1">
              <DialogPrimitive.Title
                data-testid="guide-title"
                className="text-lg font-semibold leading-tight tracking-tight sm:text-xl"
              >
                {state.status === 'loaded' ? state.metadata?.title : 'Loading…'}
              </DialogPrimitive.Title>
              <DialogPrimitive.Description
                className={cn('mt-1 text-muted-foreground', descSizeClass)}
              >
                {state.status === 'loaded'
                  ? (state.metadata?.description ?? '')
                  : state.status === 'error'
                    ? ''
                    : 'Loading walkthrough screenshots…'}
              </DialogPrimitive.Description>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {state.status === 'loaded' && state.metadata?.video && (
                <div
                  className="mr-1 flex overflow-hidden rounded-md border"
                  role="group"
                  aria-label="View mode"
                  data-testid="guide-mode-toggle"
                >
                  <button
                    type="button"
                    onClick={() => setMode('slides')}
                    aria-pressed={mode === 'slides'}
                    data-testid="guide-mode-slides"
                    className={cn(
                      'px-3 py-1.5 text-xs font-medium transition-colors',
                      mode === 'slides'
                        ? 'bg-foreground text-background'
                        : 'bg-background text-foreground hover:bg-muted',
                    )}
                  >
                    Slides
                  </button>
                  <button
                    type="button"
                    onClick={() => setMode('video')}
                    aria-pressed={mode === 'video'}
                    data-testid="guide-mode-video"
                    className={cn(
                      'border-l px-3 py-1.5 text-xs font-medium transition-colors',
                      mode === 'video'
                        ? 'bg-foreground text-background'
                        : 'bg-background text-foreground hover:bg-muted',
                    )}
                  >
                    Video
                  </button>
                </div>
              )}
              <Button
                variant="ghost"
                size="icon"
                onClick={cycleTextSize}
                data-testid="guide-text-size"
                aria-label={`Text size: ${textSize}. Click to cycle.`}
                title="Cycle text size"
              >
                <span className="font-semibold">
                  {textSize === 'sm' ? 'A−' : textSize === 'base' ? 'A' : 'A+'}
                </span>
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={toggleFullscreen}
                data-testid="guide-fullscreen"
                aria-label={fullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
                aria-pressed={fullscreen}
                title="Toggle fullscreen (f)"
              >
                {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </Button>
              <DialogPrimitive.Close asChild>
                <Button variant="ghost" size="icon" aria-label="Close guide">
                  <X className="h-4 w-4" />
                </Button>
              </DialogPrimitive.Close>
            </div>
          </div>

          {state.status === 'loading' && (
            <p className="flex-1 py-12 text-center text-sm text-muted-foreground">Loading guide…</p>
          )}

          {state.status === 'error' && (
            <p
              className="flex-1 py-12 text-center text-sm text-destructive"
              data-testid="guide-error"
            >
              Could not load guide: {state.error}
            </p>
          )}

          {state.status === 'loaded' && mode === 'video' && state.metadata?.video && (
            <div
              className="flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-md border bg-black"
              data-testid="guide-video-container"
            >
              {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
              <video
                src={`/guides/${guideId}/${state.metadata.video}`}
                controls
                autoPlay
                loop
                className="max-h-full max-w-full"
                data-testid="guide-video"
                aria-label={state.metadata.title}
              />
            </div>
          )}

          {state.status === 'loaded' && mode === 'slides' && slide && (
            <>
              {/* Image area — fills available vertical space. min-h-0 lets it
                  shrink instead of overflowing the dialog. */}
              <div className="flex min-h-0 flex-1 flex-col gap-2">
                <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-md border bg-muted">
                  {/* Plain <img> — the static PNGs under /guides/ are served
                      as-is by Next.js (no Next/Image re-encoding). */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`/guides/${guideId}/${slide.file}`}
                    alt={slide.caption}
                    className="max-h-full max-w-full object-contain"
                    data-testid="guide-slide-image"
                  />
                </div>
                <a
                  href={`/guides/${guideId}/${slide.file}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 self-start text-xs text-muted-foreground hover:text-foreground"
                  data-testid="guide-view-full"
                >
                  <ExternalLink className="h-3 w-3" />
                  View full image in new tab
                </a>
              </div>

              <p
                className={cn('shrink-0', captionSizeClass)}
                data-testid="guide-slide-caption"
                aria-live="polite"
              >
                <span className="sr-only">{`Slide ${slideIndex + 1} of ${total}: `}</span>
                {slide.caption}
              </p>

              <div className="flex shrink-0 items-center justify-between gap-2 border-t pt-3">
                <Button
                  variant="outline"
                  disabled={slideIndex === 0}
                  onClick={() => setSlideIndex((i) => Math.max(i - 1, 0))}
                  data-testid="guide-prev"
                  aria-label="Previous slide"
                >
                  Previous
                </Button>
                <span
                  className="text-sm text-muted-foreground"
                  data-testid="guide-counter"
                  aria-label={`Slide ${slideIndex + 1} of ${total}`}
                >
                  {slideIndex + 1} / {total}
                </span>
                <Button
                  variant="outline"
                  disabled={slideIndex === total - 1}
                  onClick={() => setSlideIndex((i) => Math.min(i + 1, total - 1))}
                  data-testid="guide-next"
                  aria-label="Next slide"
                >
                  Next
                </Button>
              </div>
            </>
          )}
        </DialogPrimitive.Content>
      </DialogPortal>
    </DialogPrimitive.Root>
  );
}
