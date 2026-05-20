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
import { ParamRow } from './param-row';
import { stashClearAll, stashClearRow } from './stash';
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
   * Cross-type stash (Story 2.1). Held in a `Map<string, StashEntry>`
   * passed by ref to each `<ParamRow>` so siblings share the same map
   * across the builder's lifetime. Invalidation rules in §4 are
   * enforced via the `lastBuilderWriteRef`-guarded effect below.
   */
  const stashRef = React.useRef<StashMap>(new Map());

  /**
   * Snapshot of the prior `value` prop. Used by the stash-invalidation
   * effect to identify which rows changed externally (textarea-driven)
   * and clear their stash entries. Builder-originated writes are
   * filtered out via `lastBuilderWriteRef`.
   */
  const priorValueRef = React.useRef<string>(value);

  /**
   * Pending `SearchSpaceJson` currently scheduled for debounced emit.
   * `flushBuilderWrite()` reads this so onBlur emits the latest keystroke
   * even though `value` (and therefore `parseResult`) hasn't yet
   * propagated through React's re-render cycle.
   */
  const pendingWriteRef = React.useRef<SearchSpaceJson | null>(null);

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
      pendingWriteRef.current = next;
      if (debounceRef.current !== null) {
        clearTimeout(debounceRef.current);
      }
      debounceRef.current = setTimeout(() => {
        debounceRef.current = null;
        pendingWriteRef.current = null;
        emitBuilderWrite(stringifySearchSpace(next));
      }, DEBOUNCE_MS);
    },
    [emitBuilderWrite],
  );

  /**
   * Synchronously cancel any pending debounce and emit the latest canonical
   * write. Called from `<RowNumeric>`'s `onBlur` to make onBlur writes
   * synchronous per FR-3. Reads from `pendingWriteRef` so the latest
   * keystroke's `next` is emitted even though `value` hasn't yet
   * propagated through React's re-render cycle.
   */
  const flushBuilderWrite = React.useCallback((): void => {
    if (debounceRef.current === null || pendingWriteRef.current === null) return;
    clearTimeout(debounceRef.current);
    debounceRef.current = null;
    const next = pendingWriteRef.current;
    pendingWriteRef.current = null;
    emitBuilderWrite(stringifySearchSpace(next));
  }, [emitBuilderWrite]);

  /**
   * Row-level change handler passed to `<ParamRow>` via prop drilling.
   * Composes the new `SearchSpaceJson` from the prior parsed value +
   * the row mutation, then schedules a debounced canonical write.
   */
  const onSpecChange = React.useCallback(
    (paramName: string, nextSpec: ParamSpec): void => {
      if (!parseResult.ok) return;
      const data = parseResult.data as SearchSpaceJson;
      const nextParams = { ...(data.params ?? {}), [paramName]: nextSpec };
      const next: SearchSpaceJson = { ...data, params: nextParams };
      scheduleBuilderWrite(next);
    },
    [parseResult, scheduleBuilderWrite],
  );

  /**
   * `onBlurFlush` propagates `<RowNumeric>`'s blur event up to the
   * builder, which cancels the pending debounce and emits the latest
   * canonical write synchronously. Per FR-3, on-blur writes are
   * synchronous (not debounced).
   */
  const onBlurFlush = flushBuilderWrite;

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
   *
   * Also performs stash invalidation per FR-2 / §4 invalidation rules:
   *   - If the incoming `value` matches `lastBuilderWriteRef.current`,
   *     it's a builder-originated round-trip — skip invalidation entirely.
   *   - Otherwise (textarea/Undo/auto-fill external write), diff prior
   *     vs current parsed params and `stashClearRow` for every key whose
   *     spec changed externally.
   */
  React.useEffect(() => {
    if (debounceRef.current !== null) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }

    const isBuilderRoundTrip = value === lastBuilderWriteRef.current;
    if (isBuilderRoundTrip) {
      priorValueRef.current = value;
      return;
    }

    // External write — invalidate per-row stash for any spec that changed.
    const priorParsed = parseSearchSpace(priorValueRef.current);
    const currentParsed = parseSearchSpace(value);
    if (priorParsed.ok && currentParsed.ok) {
      const priorParams = (priorParsed.data as SearchSpaceJson).params ?? {};
      const currentParams = (currentParsed.data as SearchSpaceJson).params ?? {};
      const allKeys = new Set([...Object.keys(priorParams), ...Object.keys(currentParams)]);
      for (const key of allKeys) {
        const before = JSON.stringify(priorParams[key]);
        const after = JSON.stringify(currentParams[key]);
        if (before !== after) {
          stashClearRow(stashRef.current, key);
        }
      }
    } else {
      // If either side is unparseable, conservatively clear all stash.
      stashClearAll(stashRef.current);
    }

    priorValueRef.current = value;
  }, [value]);

  /** Clear the entire stash on template change (different param namespace). */
  React.useEffect(() => {
    stashClearAll(stashRef.current);
  }, [templateBody]);

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
      {declaredKeys.map((paramName) => (
        <ParamRow
          key={paramName}
          paramName={paramName}
          declaredType={declared[paramName] ?? 'unknown'}
          spec={rowSpec(parseResult, paramName)}
          stashRef={stashRef}
          onSpecChange={onSpecChange}
          onBlurFlush={onBlurFlush}
        />
      ))}
      {paramsMissing && <BuilderPlaceholder variant="missing-params-hint" />}
    </div>
  );
}
