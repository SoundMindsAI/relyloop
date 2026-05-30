// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { Button } from '@/components/ui/button';

export interface CursorPaginatorProps {
  hasMore: boolean;
  onNext?: () => void;
  /** Provide only if Prev navigation is possible (cursor stack is non-empty beyond root). */
  onPrev?: () => void;
  pageSize: number;
  onPageSizeChange: (size: number) => void;
  totalCount?: number | undefined;
  pageSizeOptions?: readonly number[];
}

const DEFAULT_PAGE_SIZE_OPTIONS = [50, 100, 200] as const;

export function CursorPaginator({
  hasMore,
  onNext,
  onPrev,
  pageSize,
  onPageSizeChange,
  totalCount,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
}: CursorPaginatorProps) {
  return (
    <div className="flex items-center justify-between gap-4 pt-4 text-sm">
      <div className="flex items-center gap-2 text-gray-600">
        <label htmlFor="page-size" className="text-sm">
          Page size
        </label>
        <select
          id="page-size"
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="rounded-md border border-gray-200 bg-white px-2 py-1"
          data-testid="page-size-select"
        >
          {pageSizeOptions.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        {totalCount != null && (
          <span data-testid="total-count">· {totalCount.toLocaleString()} total</span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onPrev}
          disabled={!onPrev}
          data-testid="paginator-prev"
        >
          Prev
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onNext}
          disabled={!hasMore || !onNext}
          data-testid="paginator-next"
        >
          Next
        </Button>
      </div>
    </div>
  );
}
