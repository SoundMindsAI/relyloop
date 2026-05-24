'use client';

import { useMemo } from 'react';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useTemplate } from '@/lib/api/query-templates';
import type { FollowupKind } from '@/lib/enums';
import type { components } from '@/lib/types';

// feat_digest_executable_followups Story 5.1 — rewrite the panel to
// branch per discriminated-union ``FollowupItem`` kind. ``narrow`` and
// ``widen`` items carry a ``search_space`` body and surface as
// actionable "Run this followup" cards; ``text`` items render as
// rationale-only suggestion cards. The legacy ``?hypothesis=`` link is
// retired per FR-12.
//
// feat_digest_executable_followups_swap_template Stories 3.1 + 3.2:
// widen the per-kind branching to the 4th ``swap_template`` variant
// via exhaustive ``Record<FollowupKind, …>`` lookups (D-28). The
// swap_template card is rendered by ``SwapTemplateCard`` (a same-file
// child component) so each card can call ``useTemplate(followup.template_id)``
// at its own top level — satisfies React Rules of Hooks AND scales to
// N distinct swap targets per digest (GPT-5.5 cycle-1 F2/F3 fix).

export type FollowupItem = components['schemas']['FollowupItem'];

type SwapTemplateFollowup = Extract<FollowupItem, { kind: 'swap_template' }>;

export interface SuggestedFollowupsPanelProps {
  followups: readonly FollowupItem[];
  /**
   * Called with the 0-based index when the operator clicks "Run this followup".
   * The page-level orchestrator (Story 5.2) is responsible for opening the
   * CreateStudyModal with the appropriate ``initialValues``.
   */
  onRun: (index: number) => void;
  /**
   * Parent study's ``search_space`` for the diff view. Optional — when omitted
   * (e.g., still loading from a lazy useStudy call), the per-card "Show
   * search space" expander falls back to rendering the proposed search-space
   * JSON without a diff comparison.
   */
  parentSearchSpace?: Record<string, unknown>;
  /** Loading flag for the lazy parent-study fetch. */
  parentStudyLoading?: boolean;
  /** Non-null error from the lazy parent-study fetch. */
  parentStudyError?: unknown;
  /**
   * Parent query template (declared_params subset) for the swap_template
   * declared-params diff. Populated by the page-level orchestrator via a
   * lazy ``useTemplate(parentStudy.data?.template_id)`` call. When
   * undefined, the card renders a loading message.
   */
  parentTemplate?: { declared_params: Record<string, string> } | undefined;
  parentTemplateLoading?: boolean;
  parentTemplateError?: unknown;
}

// Values must match backend/app/domain/study/followups.py FollowupItem.kind.
const KIND_LABELS: Record<FollowupKind, string> = {
  narrow: 'Narrow',
  widen: 'Widen',
  text: 'Suggestion',
  swap_template: 'Swap template',
};

// Per-kind UI behavior lookups (D-28 exhaustive — TypeScript fails when a
// future variant is added without a corresponding entry).
const SHOWS_SEARCH_SPACE_EXPANDER: Record<FollowupKind, boolean> = {
  narrow: true,
  widen: true,
  text: false,
  swap_template: true,
};

const SHOWS_RUN_BUTTON: Record<FollowupKind, boolean> = {
  narrow: true,
  widen: true,
  text: false,
  swap_template: true,
};

const SHOWS_DECLARED_PARAMS_DIFF: Record<FollowupKind, boolean> = {
  narrow: false,
  widen: false,
  text: false,
  swap_template: true,
};

export function SuggestedFollowupsPanel({
  followups,
  onRun,
  parentSearchSpace,
  parentStudyLoading = false,
  parentStudyError = null,
  parentTemplate,
  parentTemplateLoading = false,
  parentTemplateError = null,
}: SuggestedFollowupsPanelProps) {
  if (followups.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1 text-base">
          Suggested follow-ups
          <InfoTooltip glossaryKey="proposal.suggested_followups" />
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-3" data-testid="suggested-followups-list">
          {followups.map((f, i) => {
            if (f.kind === 'swap_template') {
              return (
                <SwapTemplateCard
                  key={`followup-${i}`}
                  followup={f}
                  index={i}
                  parentTemplate={parentTemplate}
                  parentTemplateLoading={parentTemplateLoading}
                  parentTemplateError={parentTemplateError}
                  onRun={onRun}
                />
              );
            }
            return (
              <li
                key={`followup-${i}`}
                data-testid={`followup-${i}-card`}
                className="rounded-md border p-3 space-y-2"
              >
                <div className="flex items-center gap-2">
                  <Badge variant="outline" aria-label={KIND_LABELS[f.kind]}>
                    {KIND_LABELS[f.kind]}
                  </Badge>
                  <InfoTooltip glossaryKey={`proposal.followup_kind_${f.kind}` as const} />
                </div>
                <p className="text-sm">{f.rationale}</p>
                {SHOWS_SEARCH_SPACE_EXPANDER[f.kind] && (
                  <details className="text-xs">
                    <summary
                      className="cursor-pointer text-gray-700 hover:text-gray-900"
                      data-testid={`followup-${i}-show-search-space`}
                    >
                      Show search space
                      <span className="ml-1 inline-block align-middle">
                        <InfoTooltip glossaryKey="proposal.followup_search_space_diff" />
                      </span>
                    </summary>
                    <div className="mt-2 space-y-2">
                      {parentStudyLoading && (
                        <p
                          className="text-xs text-gray-500"
                          data-testid={`followup-${i}-search-space-loading`}
                        >
                          Loading parent search space...
                        </p>
                      )}
                      {parentStudyError !== null && parentStudyError !== undefined && (
                        <p
                          className="text-xs text-gray-500"
                          data-testid={`followup-${i}-search-space-error`}
                        >
                          Could not load parent — showing proposed bounds only.
                        </p>
                      )}
                      {parentSearchSpace !== undefined && (
                        <div data-testid={`followup-${i}-parent-search-space`}>
                          <p className="text-xs font-semibold text-gray-700">Parent (current):</p>
                          <pre className="text-xs bg-muted p-2 rounded overflow-x-auto">
                            {JSON.stringify(parentSearchSpace, null, 2)}
                          </pre>
                        </div>
                      )}
                      <div data-testid={`followup-${i}-proposed-search-space`}>
                        <p className="text-xs font-semibold text-gray-700">Proposed:</p>
                        <pre className="text-xs bg-muted p-2 rounded overflow-x-auto">
                          {JSON.stringify(f.search_space, null, 2)}
                        </pre>
                      </div>
                    </div>
                  </details>
                )}
                {SHOWS_RUN_BUTTON[f.kind] && (
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      variant="default"
                      size="sm"
                      data-testid={`followup-${i}-run`}
                      onClick={() => onRun(i)}
                      aria-label="Run this followup — opens the create study form pre-filled with these settings"
                    >
                      Run this followup
                      <span className="ml-1 inline-block align-middle">
                        <InfoTooltip glossaryKey="proposal.followup_run_button" />
                      </span>
                    </Button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

interface SwapTemplateCardProps {
  followup: SwapTemplateFollowup;
  index: number;
  parentTemplate?: { declared_params: Record<string, string> } | undefined;
  parentTemplateLoading?: boolean;
  parentTemplateError?: unknown;
  onRun: (index: number) => void;
}

/**
 * Same-file child component for the ``swap_template`` followup card.
 *
 * Per-card ``useTemplate(followup.template_id)`` call at the top level
 * satisfies React Rules of Hooks AND scales to N distinct swap targets
 * within one digest (GPT-5.5 cycle-1 F2/F3 fix vs. parent-passed lookup
 * map). The page orchestrator only needs to pass the parent template
 * data (single fetch) — every swap-target fetch lives here.
 */
function SwapTemplateCard({
  followup,
  index,
  parentTemplate,
  parentTemplateLoading = false,
  parentTemplateError = null,
  onRun,
}: SwapTemplateCardProps) {
  const swapTargetQuery = useTemplate(followup.template_id);
  const swapTarget = swapTargetQuery.data;
  const swapTargetLoading = swapTargetQuery.isLoading;
  const swapTargetError = swapTargetQuery.error;

  const sharedKeys = useMemo(() => {
    if (!parentTemplate || !swapTarget) return [];
    const swapDeclared = swapTarget.declared_params ?? {};
    return Object.keys(parentTemplate.declared_params)
      .filter((k) => k in swapDeclared)
      .sort();
  }, [parentTemplate, swapTarget]);

  return (
    <li
      key={`followup-${index}`}
      data-testid={`followup-${index}-card`}
      className="rounded-md border p-3 space-y-2"
    >
      <div className="flex items-center gap-2">
        <Badge variant="outline" aria-label={KIND_LABELS.swap_template}>
          {KIND_LABELS.swap_template}
        </Badge>
        <InfoTooltip glossaryKey="proposal.followup_kind_swap_template" />
      </div>
      <p className="text-sm">{followup.rationale}</p>

      <details className="text-xs" data-testid={`followup-${index}-declared-params-diff`}>
        <summary
          className="cursor-pointer text-gray-700 hover:text-gray-900"
          data-testid={`followup-${index}-show-declared-params`}
        >
          Show declared params
          <span className="ml-1 inline-block align-middle">
            <InfoTooltip glossaryKey="proposal.followup_declared_params_diff" />
          </span>
        </summary>
        <div className="mt-2 grid grid-cols-2 gap-3">
          <DeclaredParamsColumn
            title="Parent template"
            params={parentTemplate?.declared_params}
            shared={sharedKeys}
            loading={parentTemplateLoading}
            error={parentTemplateError}
            testId={`followup-${index}-parent-declared-params`}
          />
          <DeclaredParamsColumn
            title="Swap target"
            params={swapTarget?.declared_params}
            shared={sharedKeys}
            loading={swapTargetLoading}
            error={swapTargetError ?? null}
            testId={`followup-${index}-swap-declared-params`}
          />
        </div>
      </details>

      {/* Show search space — proposed JSON only, no parent diff column
          (parent's bounds are over a different param set; not directly comparable). */}
      <details className="text-xs">
        <summary
          className="cursor-pointer text-gray-700 hover:text-gray-900"
          data-testid={`followup-${index}-show-search-space`}
        >
          Show search space
          <span className="ml-1 inline-block align-middle">
            <InfoTooltip glossaryKey="proposal.followup_search_space_diff" />
          </span>
        </summary>
        <pre className="mt-2 text-xs bg-muted p-2 rounded overflow-x-auto">
          {JSON.stringify(followup.search_space, null, 2)}
        </pre>
      </details>

      <div className="flex justify-end">
        <Button
          type="button"
          variant="default"
          size="sm"
          data-testid={`followup-${index}-run`}
          onClick={() => onRun(index)}
          aria-label="Run this followup — opens the create study form pre-filled with these settings"
        >
          Run this followup
          <span className="ml-1 inline-block align-middle">
            <InfoTooltip glossaryKey="proposal.followup_run_button" />
          </span>
        </Button>
      </div>
    </li>
  );
}

interface DeclaredParamsColumnProps {
  title: string;
  params?: Record<string, string>;
  shared: readonly string[];
  loading: boolean;
  error: unknown;
  testId: string;
}

function DeclaredParamsColumn({
  title,
  params,
  shared,
  loading,
  error,
  testId,
}: DeclaredParamsColumnProps) {
  return (
    <div data-testid={testId}>
      <p className="text-xs font-semibold text-gray-700">{title}</p>
      {loading && (
        <p className="text-xs text-gray-500" data-testid={`${testId}-loading`}>
          Loading template details…
        </p>
      )}
      {!loading && error !== null && error !== undefined && (
        <p className="text-xs text-gray-500" data-testid={`${testId}-error`}>
          Could not load template details — submitting will still work; the comparison view is
          unavailable.
        </p>
      )}
      {!loading && (error === null || error === undefined) && params !== undefined && (
        <ul className="mt-1 space-y-0.5">
          {Object.entries(params)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([name, type]) => {
              const isShared = shared.includes(name);
              return (
                <li
                  key={name}
                  className={isShared ? 'font-semibold text-gray-900' : 'text-gray-700'}
                  data-shared={isShared ? 'true' : 'false'}
                >
                  <code className="text-xs">{name}</code>: {type}
                </li>
              );
            })}
        </ul>
      )}
    </div>
  );
}
