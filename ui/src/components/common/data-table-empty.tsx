'use client';

/**
 * Empty-state shapes for `<DataTable>` (feat_data_table_primitive Story 2.7).
 *
 * Story 2.1 scaffold — declares the three empty-state kinds + a minimal render
 * that does NOT yet wire `onClearFilters` / `onReturnToFirstPage` actions. The
 * full conditional rendering (no-rows-match / no-rows-exist / stale-cursor)
 * lands in Story 2.7. The scaffold keeps the surface area frozen so consumers
 * in Epic 3 can write their `emptyStateNoRows` props without rework later.
 */

import type * as React from 'react';

import { Button } from '@/components/ui/button';

export type DataTableEmptyKind = 'no-rows-match' | 'no-rows-exist' | 'stale-cursor';

export interface DataTableEmptyProps {
  kind: DataTableEmptyKind;
  /** Required for `no-rows-exist`; ignored for the other two. */
  title?: string;
  /** Required for `no-rows-exist` and `no-rows-match`; ignored for `stale-cursor`. */
  message?: string;
  /** Primary CTA for `no-rows-exist` (e.g. "Register cluster"). */
  primaryCta?: React.ReactNode;
  /** Primitive-supplied action for `no-rows-match`. */
  onClearFilters?: () => void;
  /** Primitive-supplied action for `stale-cursor`. */
  onReturnToFirstPage?: () => void;
  /** E2E testid; defaults to `data-table-empty-<kind>`. */
  testid?: string;
}

const FALLBACK_COPY: Record<DataTableEmptyKind, { title: string; message: string }> = {
  'no-rows-match': {
    title: 'No matching rows',
    message: 'No rows match the current filter or search.',
  },
  'no-rows-exist': {
    title: 'No rows yet',
    message: 'This collection is empty.',
  },
  'stale-cursor': {
    title: 'This page is no longer available',
    message: 'Rows shifted while you were paginating. Return to the first page.',
  },
};

export function DataTableEmpty({
  kind,
  title,
  message,
  primaryCta,
  onClearFilters,
  onReturnToFirstPage,
  testid,
}: DataTableEmptyProps) {
  const fallback = FALLBACK_COPY[kind];
  const displayTitle = title ?? fallback.title;
  const displayMessage = message ?? fallback.message;
  const computedTestid = testid ?? `data-table-empty-${kind}`;
  return (
    <div
      data-testid={computedTestid}
      className="flex flex-col items-center gap-3 py-12 text-center"
    >
      <p className="text-sm font-medium">{displayTitle}</p>
      <p className="text-sm text-muted-foreground">{displayMessage}</p>
      {kind === 'no-rows-exist' && primaryCta}
      {kind === 'no-rows-match' && onClearFilters && (
        <Button
          variant="outline"
          size="sm"
          onClick={onClearFilters}
          data-testid="data-table-empty-clear-filters"
        >
          Clear filters
        </Button>
      )}
      {kind === 'stale-cursor' && onReturnToFirstPage && (
        <Button
          variant="outline"
          size="sm"
          onClick={onReturnToFirstPage}
          data-testid="data-table-empty-return-to-first-page"
        >
          Return to first page
        </Button>
      )}
    </div>
  );
}
