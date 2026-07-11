// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * `<DetailPageShell>` — shared loading / error / data scaffold for
 * `/{entity}/[id]` detail pages.
 *
 * Wraps a TanStack `UseQueryResult<T, ApiError>` and renders the appropriate
 * state. Before this primitive, six detail pages
 * (`clusters/[id]`, `studies/[id]`, `proposals/[id]`, `query-sets/[id]`,
 * `templates/[id]`, `judgments/[id]`) hand-rolled the same `isPending →
 * isError → data` ternary with identical className strings and slightly
 * inconsistent copy ("deleted" vs "removed") and only one page
 * (`proposals/[id]`) bothered to distinguish 404 from network error.
 *
 * This primitive flattens that — the 404 vs network discrimination happens
 * in one place, controlled by `notFoundErrorCode`. Consumers just write the
 * happy-path render.
 *
 * ## API shape (Q2 locked: children-as-function)
 *
 * ```tsx
 * <DetailPageShell
 *   query={studyQ}
 *   entityLabel="study"
 *   notFoundErrorCode="STUDY_NOT_FOUND"
 * >
 *   {(study) => (
 *     <>
 *       <StudyHeader study={study} />
 *       <TrialsTable studyId={study.id} />
 *     </>
 *   )}
 * </DetailPageShell>
 * ```
 *
 * ## Behavior
 *
 * - `query.isPending` → `<Card><CardContent><p>Loading…</p></CardContent></Card>` placeholder.
 * - `query.isError && error.errorCode === notFoundErrorCode` →
 *   `<EmptyState title="{Entity} not found" message="The {entity} may have been deleted." />`.
 * - `query.isError && error.errorCode !== notFoundErrorCode` (network / 5xx) →
 *   `<EmptyState title="Backend unreachable" message="Refresh after re-launching the API." />`.
 * - `query.data` defined → invoke `children(data)`.
 *
 * ## Copy normalization
 *
 * Default 404 message is "The {entity} may have been deleted." — replacing
 * the templates / judgments "may have been removed" variant per the
 * `chore_detail_page_shell_primitive` idea: "deleted" is the majority
 * (4 of 6 pre-migration sites) and matches the soft-delete data model.
 */

import { type UseQueryResult } from '@tanstack/react-query';

import { EmptyState } from '@/components/common/empty-state';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { type ApiError } from '@/lib/api-errors';

export interface DetailPageShellProps<T> {
  /**
   * TanStack query result for the detail entity. The primitive reads
   * `isPending`, `isError`, `error`, and `data` — the rest of the result
   * surface stays available to the consumer if it needs it.
   */
  query: UseQueryResult<T, ApiError>;
  /**
   * Singular entity label, e.g. `"study"` / `"cluster"` / `"query set"`.
   * Used in the default copy: title is title-cased (`"Study not found"`)
   * and message uses the raw form (`"The study may have been deleted."`).
   */
  entityLabel: string;
  /**
   * Optional title override. When omitted, defaults to title-casing
   * `entityLabel`. Provide this when title-casing would produce awkward
   * results (e.g. `entityLabel="judgment list"` would title-case to
   * `"Judgment list not found"`, which is correct here, but a longer
   * label like `"judgment list"` might want explicit `entityTitle="Judgment List"`
   * for header styling).
   */
  entityTitle?: string;
  /**
   * Backend `error_code` that identifies the 404-equivalent for this
   * resource (e.g. `"STUDY_NOT_FOUND"`). Per `api-errors.ts`, RelyLoop's
   * `ApiError` discriminates by string code, not HTTP status — providers
   * still ship a 404 status, but the routing predicate is the code.
   */
  notFoundErrorCode: string;
  /**
   * Optional override for the 404 message. Defaults to
   * `"The {entityLabel} may have been deleted."`.
   */
  notFoundMessage?: string;
  /**
   * Optional override for the non-404 error message. Defaults to
   * `"Refresh after re-launching the API."`.
   */
  unreachableMessage?: string;
  /**
   * Optional: derive the browser `document.title` from the loaded entity
   * (e.g. `(study) => study.name`). Applied once data resolves and restored on
   * unmount, so tabs/history/bookmarks are named instead of a bare "RelyLoop".
   */
  documentTitle?: (data: T) => string;
  /**
   * Render function invoked with the loaded data. Per Q2's locked
   * decision: children-as-function rather than compound component —
   * simpler signature, matches the existing `<EntitySelect>` feel.
   */
  children: (data: T) => React.ReactNode;
}

function titleCase(label: string): string {
  if (!label) return label;
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export function DetailPageShell<T>(props: DetailPageShellProps<T>) {
  const {
    query,
    entityLabel,
    entityTitle,
    notFoundErrorCode,
    notFoundMessage,
    unreachableMessage,
    documentTitle,
    children,
  } = props;

  // Hooks must run before the early returns; null title leaves the tab
  // untouched until the entity name is known.
  useDocumentTitle(query.data && documentTitle ? documentTitle(query.data) : null);

  if (query.isPending) {
    // Skeleton sized to a typical detail header + body so the layout doesn't
    // jump when the real content arrives.
    return (
      <Card>
        <CardContent className="space-y-4 py-6" role="status" aria-label="Loading">
          <Skeleton className="h-7 w-1/3" />
          <Skeleton className="h-4 w-2/3" />
          <div className="space-y-2 pt-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-4/6" />
          </div>
          <span className="sr-only">Loading…</span>
        </CardContent>
      </Card>
    );
  }

  if (query.isError) {
    const title = entityTitle ?? titleCase(entityLabel);
    if (query.error?.errorCode === notFoundErrorCode) {
      return (
        <EmptyState
          title={`${title} not found`}
          message={notFoundMessage ?? `The ${entityLabel} may have been deleted.`}
        />
      );
    }
    return (
      <EmptyState
        title="Backend unreachable"
        message={unreachableMessage ?? 'Refresh after re-launching the API.'}
      />
    );
  }

  // Loose null check catches both `undefined` (initial fetch) and `null`
  // (a 200 OK with a null body) — per Gemini PR #155 review, defense
  // against accidentally invoking `children(null)` and crashing on
  // property access in the consumer.
  if (query.data == null) {
    return null;
  }

  return <>{children(query.data)}</>;
}
