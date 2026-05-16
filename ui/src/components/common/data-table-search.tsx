'use client';

/**
 * Debounced text-search input for `<DataTable>` (feat_data_table_primitive
 * Story 2.4 / FR-6).
 *
 * Renders a `<label>` + `<input>` in the toolbar. Local state holds the
 * uncommitted draft; after 300ms of inactivity the debounced value is
 * compared against the bounds and `onQChange(value | null)` fires.
 *
 * Boundary handling (per AC-3 + cycle-3 F4):
 * - Initial under-length input (no active q) → no call.
 * - Reaching 2+ chars → `onQChange(value)`.
 * - Editing an existing q down below 2 chars → `onQChange(null)` so stale
 *   `?q=` doesn't stick in the URL.
 * - Clearing the input entirely → `onQChange(null)`.
 */

import { useEffect, useRef, useState } from 'react';
import { z } from 'zod';

import { Input } from '@/components/ui/input';

import { useDebouncedValue } from '@/hooks/use-debounced-value';

const QSchema = z.string().min(2).max(200);

export interface DataTableSearchProps {
  /** Currently-active `?q=` value from URL state (`null` when empty). */
  value: string | null;
  onQChange: (next: string | null) => void;
  /** Default 300ms per FR-6; overrideable for tests. */
  debounceMs?: number;
  /** Optional row-count indicator rendered after the input. */
  totalCount?: number;
  /** Custom placeholder; defaults to "Search…". */
  placeholder?: string;
}

export function DataTableSearch({
  value,
  onQChange,
  debounceMs = 300,
  totalCount,
  placeholder = 'Search…',
}: DataTableSearchProps) {
  const [draft, setDraft] = useState(value ?? '');
  const debouncedDraft = useDebouncedValue(draft, debounceMs);
  const lastCommittedRef = useRef<string | null>(value);

  // Sync the local draft when the controlled `value` prop changes externally
  // (back/forward navigation, programmatic URL update). Without this, the
  // input would show stale text after Back from a page that had `?q=foo`.
  useEffect(() => {
    if (value !== lastCommittedRef.current) {
      setDraft(value ?? '');
      lastCommittedRef.current = value;
    }
  }, [value]);

  useEffect(() => {
    // Recompute the commit decision from the debounced draft.
    const parsed = QSchema.safeParse(debouncedDraft);
    const next: string | null = parsed.success ? parsed.data : null;
    if (next === lastCommittedRef.current) {
      // No change vs. last committed value — avoid double-firing on initial mount.
      return;
    }
    // When the draft is under length AND there's no prior committed value,
    // skip the call (user hasn't typed enough to search yet).
    if (next === null && lastCommittedRef.current === null) {
      return;
    }
    lastCommittedRef.current = next;
    onQChange(next);
  }, [debouncedDraft, onQChange]);

  return (
    <div className="flex items-center gap-2">
      <label htmlFor="data-table-search-input" className="sr-only">
        Search
      </label>
      <Input
        id="data-table-search-input"
        type="search"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={placeholder}
        className="h-8 w-56"
        data-testid="data-table-search"
      />
      {value !== null && totalCount !== undefined && (
        <span
          className="text-xs text-muted-foreground"
          data-testid="data-table-search-result-count"
        >
          ({totalCount.toLocaleString()} results)
        </span>
      )}
    </div>
  );
}
