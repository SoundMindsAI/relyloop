// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { usePathname } from 'next/navigation';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { GuideViewer } from './guide-viewer';
import { guidesForPath } from './guide-types';

/**
 * Floating "?" button (bottom-right) that opens the contextual GuideViewer.
 * Reads the current pathname and surfaces guides registered for that prefix
 * via GUIDE_MAP. When multiple guides match the route, the user picks one
 * from a popover before the viewer opens.
 *
 * Hidden when no guides match — keeps the button from cluttering pages
 * (e.g., the /guide catalog itself, or future admin routes) that don't have
 * a registered walkthrough.
 */
export function GuideTrigger() {
  const pathname = usePathname();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [viewerGuideId, setViewerGuideId] = useState<string | null>(null);

  const matches = guidesForPath(pathname);

  // Don't render on the catalog page — the catalog has its own per-guide
  // entry points and the floating button would be visual noise there.
  if (pathname.startsWith('/guide') || matches.length === 0) return null;

  function openGuide(guideId: string) {
    setViewerGuideId(guideId);
    setPickerOpen(false);
  }

  return (
    <>
      {matches.length === 1 ? (
        <Button
          variant="default"
          size="icon"
          className="fixed bottom-[max(1.5rem,env(safe-area-inset-bottom))] right-[max(1.5rem,env(safe-area-inset-right))] z-50 size-14 rounded-full text-lg shadow-lg"
          onClick={() => openGuide(matches[0]!.guideId)}
          data-testid="guide-trigger"
          aria-label={`Open guide: ${matches[0]!.label}`}
        >
          ?
        </Button>
      ) : (
        <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
          <PopoverTrigger asChild>
            <Button
              variant="default"
              size="icon"
              className="fixed bottom-[max(1.5rem,env(safe-area-inset-bottom))] right-[max(1.5rem,env(safe-area-inset-right))] z-50 size-14 rounded-full text-lg shadow-lg"
              data-testid="guide-trigger"
              aria-label="Open guide picker"
            >
              ?
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-72">
            <p className="mb-2 text-sm font-medium">Guides for this page</p>
            <ul className="space-y-1" data-testid="guide-picker-list">
              {matches.map((m) => (
                <li key={`${m.prefix}|${m.guideId}`}>
                  <button
                    type="button"
                    className="w-full rounded px-2 py-1.5 text-left text-sm hover:bg-muted"
                    onClick={() => openGuide(m.guideId)}
                    data-testid={`guide-picker-item-${m.guideId}`}
                  >
                    {m.label}
                  </button>
                </li>
              ))}
            </ul>
          </PopoverContent>
        </Popover>
      )}

      {viewerGuideId && (
        <GuideViewer
          guideId={viewerGuideId}
          open={viewerGuideId !== null}
          onOpenChange={(open) => {
            if (!open) setViewerGuideId(null);
          }}
        />
      )}
    </>
  );
}
