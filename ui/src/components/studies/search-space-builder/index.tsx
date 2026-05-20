/**
 * `<SearchSpaceBuilder>` — visual editor for Step 4 of the create-study modal.
 *
 * Story 1.1 surface: parse/stringify discipline, placeholder cascade,
 * canonicalize-on-mount effect, single debounce boundary. Rows are
 * placeholder containers in Story 1.1 (per-row content arrives in 1.2;
 * editable controls in Epic 2).
 *
 * Round-trip discipline (spec FR-9 + AC-7 + §4 product principles):
 *   - Builder reads `value` (textarea string) on every render.
 *   - Builder writes back via `onChange(canonicalJson)` through a single
 *     200ms debounce timer + a synchronous `flushBuilderWrite()` helper.
 *   - Every builder-originated write sets `lastBuilderWriteRef` BEFORE
 *     calling `onChange`, so the textarea-driven `value` change detector
 *     (Story 2.1) can skip stash invalidation when the new `value` equals
 *     our own emission.
 *   - Canonicalize-on-mount: on first render, if parseable and the
 *     stringified canonical form differs from the input, emit one
 *     normalized write. This is the mechanism the round-trip parity test
 *     exercises.
 */

'use client';

import * as React from 'react';

import type { QueryTemplateDetail } from '@/lib/api/query-templates';

import { BuilderPlaceholder } from './placeholder';
import type { ParamSpec, SearchSpaceJson, StashMap } from './types';

const DEBOUNCE_MS = 200;

export interface SearchSpaceBuilderProps {
  value: string;
  onChange: (next: string) => void;
  templateBody: QueryTemplateDetail | null;
  templateId: string | undefined;
  templateFetchStatus: 'idle' | 'ok' | '404' | 'transient';
}

type ParseResult =
  | { ok: true; data: SearchSpaceJson | ({ params?: undefined } & Record<string, unknown>) }
  | { ok: false; error: string };

/**
 * Parse the textarea string into a `SearchSpaceJson`-shaped object.
 *
 * - `""` and `"{}"` parse as the empty object `{}` (no `params` key).
 * - `"{params:{}}"` parses with an empty `params` map.
 * - Malformed JSON returns `{ ok: false, error }`.
 *
 * Pure function; no side effects. Exported for the round-trip parity test.
 */
export function parseSearchSpace(text: string): ParseResult {
  const trimmed = text.trim();
  if (trimmed === '') return { ok: true, data: {} };
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { ok: false, error: 'expected a JSON object' };
    }
    return { ok: true, data: parsed as SearchSpaceJson };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

/**
 * Stringify a `SearchSpaceJson` with the canonical 2-space indent.
 * Exported for the round-trip parity test.
 */
export function stringifySearchSpace(data: SearchSpaceJson): string {
  return JSON.stringify(data, null, 2);
}

/** Get the row spec for `paramName` from a parsed object, or undefined. */
function rowSpec(parsed: ParseResult, paramName: string): ParamSpec | undefined {
  if (!parsed.ok) return undefined;
  const params = (parsed.data as SearchSpaceJson).params;
  if (!params) return undefined;
  return params[paramName];
}

export function SearchSpaceBuilder({
  value,
  onChange,
  templateBody,
  templateId,
  templateFetchStatus,
}: SearchSpaceBuilderProps): React.ReactElement {
  // ---- Refs (component-instance-scoped; reset on unmount) ----------------

  /** Pending debounce timer for builder→textarea writes. */
  const debounceRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  /**
   * Last canonical JSON the builder emitted. Set BEFORE calling `onChange`.
   * Story 2.1's stash invalidation effect compares incoming `value` against
   * this ref to skip clearing the stash on builder-originated round-trips.
   */
  const lastBuilderWriteRef = React.useRef<string | null>(null);

  /**
   * Cross-type stash (Story 2.1). Initialized here so siblings can read/
   * write via `stash.ts` helpers without each constructing their own ref.
   */
  const stashRef = React.useRef<StashMap>(new Map());
  // Silence unused warning until Story 2.1 wires it; deliberate.
  void stashRef;

  /** Memoized parse of the current `value`. */
  const parseResult = React.useMemo<ParseResult>(() => parseSearchSpace(value), [value]);

  // ---- Builder write helpers ---------------------------------------------

  const emitBuilderWrite = React.useCallback(
    (canonicalJson: string): void => {
      lastBuilderWriteRef.current = canonicalJson;
      onChange(canonicalJson);
    },
    [onChange],
  );

  /** Schedule a debounced canonical write. Last call wins. */
  const scheduleBuilderWrite = React.useCallback(
    (next: SearchSpaceJson): void => {
      if (debounceRef.current !== null) {
        clearTimeout(debounceRef.current);
      }
      debounceRef.current = setTimeout(() => {
        debounceRef.current = null;
        emitBuilderWrite(stringifySearchSpace(next));
      }, DEBOUNCE_MS);
    },
    [emitBuilderWrite],
  );

  /**
   * Synchronously cancel any pending debounce and emit the latest canonical
   * write. Used by `<RowNumeric>`'s `onBlurFlush` callback in Story 2.1.
   */
  const flushBuilderWrite = React.useCallback(
    (next: SearchSpaceJson): void => {
      if (debounceRef.current !== null) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
      emitBuilderWrite(stringifySearchSpace(next));
    },
    [emitBuilderWrite],
  );

  // Suppress "unused" lint until Stories 1.2 / 2.1 consume these helpers.
  void scheduleBuilderWrite;
  void flushBuilderWrite;

  // ---- Effects -----------------------------------------------------------

  /** Cancel pending debounce on unmount. */
  React.useEffect(() => {
    return () => {
      if (debounceRef.current !== null) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
    };
  }, []);

  /**
   * Cancel any pending debounce when `value` changes externally (textarea-
   * driven update). Last-edit-wins per FR-9: a textarea keystroke
   * supersedes the builder's pending write.
   */
  React.useEffect(() => {
    if (debounceRef.current !== null) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
  }, [value]);

  /**
   * Canonicalize-on-mount: if the current `value` is parseable but its
   * canonical string form differs from the input, emit one normalized
   * write so the textarea + builder state agree on the canonical
   * representation. Fixtures like `{"high": 10.0}` get normalized to
   * `{"high": 10}` on first pass; subsequent re-parses are idempotent.
   *
   * Runs once per mount. Will not retrigger on `value` change because the
   * deps array intentionally excludes `value` — this is the FIRST canonical
   * pass only; subsequent canonicalization happens via the row-edit path.
   */
  React.useEffect(() => {
    if (!parseResult.ok) return;
    // Treat `value === ''` as "nothing to canonicalize" — the placeholder
    // cascade renders the no-template hint instead.
    if (value.trim() === '') return;
    const data = parseResult.data as SearchSpaceJson;
    const canonical = stringifySearchSpace(data);
    if (canonical !== value) {
      emitBuilderWrite(canonical);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Placeholder cascade (FR-9 + spec §11) -----------------------------

  if (!parseResult.ok) {
    return (
      <div className="space-y-2" data-testid="cs-search-space-builder">
        <BuilderPlaceholder variant="parse-error" />
      </div>
    );
  }

  if (templateBody === null) {
    // Distinguish "fetch failed" (AC-11) from "no selection".
    const variant = templateFetchStatus === 'transient' ? 'transient' : 'no-template';
    return (
      <div className="space-y-2" data-testid="cs-search-space-builder">
        <BuilderPlaceholder variant={variant} />
      </div>
    );
  }

  // templateBody resolved → render declared-param rows. Row identity comes
  // from `templateBody.declared_params` keys (spec FR-1).
  const declared = templateBody.declared_params ?? {};
  const declaredKeys = Object.keys(declared);
  const data = parseResult.data as SearchSpaceJson;
  const paramsMissing = data.params === undefined && declaredKeys.length > 0;

  return (
    <div className="space-y-2" data-testid="cs-search-space-builder">
      {/*
        Story 1.1: rows are placeholder containers ("row content arrives in
        Story 1.2"). Real row markup, the type selector, low/high inputs,
        log toggle, chip input, and cardinality counters arrive in 1.2 + 2.x.
      */}
      {declaredKeys.map((paramName) => {
        const spec = rowSpec(parseResult, paramName);
        return (
          <div
            key={paramName}
            data-testid={`cs-param-row-${paramName}`}
            className="rounded-md border border-border bg-card p-3 text-sm space-y-1"
          >
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs px-1.5 py-0.5 rounded border border-border bg-background">
                {paramName}
              </span>
              <span className="text-xs text-muted-foreground">
                ({declared[paramName] ?? 'unknown'})
              </span>
            </div>
            <div className="text-xs text-muted-foreground">
              type: <span className="font-mono">{spec?.type ?? 'unset'}</span>
            </div>
          </div>
        );
      })}
      {paramsMissing && <BuilderPlaceholder variant="missing-params-hint" />}
    </div>
  );
}
