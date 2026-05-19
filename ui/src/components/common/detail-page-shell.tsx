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
    children,
  } = props;

  if (query.isPending) {
    return (
      <Card>
        <CardContent>
          <p className="py-12 text-center text-sm text-muted-foreground">Loading…</p>
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

  if (query.data === undefined) {
    return null;
  }

  return <>{children(query.data)}</>;
}
