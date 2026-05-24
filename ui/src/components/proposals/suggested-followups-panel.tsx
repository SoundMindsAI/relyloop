'use client';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { FollowupKind } from '@/lib/enums';
import type { components } from '@/lib/types';

// feat_digest_executable_followups Story 5.1 — rewrite the panel to
// branch per discriminated-union ``FollowupItem`` kind. ``narrow`` and
// ``widen`` items carry a ``search_space`` body and surface as
// actionable "Run this followup" cards; ``text`` items render as
// rationale-only suggestion cards. The legacy ``?hypothesis=`` link is
// retired per FR-12.

export type FollowupItem = components['schemas']['FollowupItem'];

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
}

// Values must match backend/app/domain/study/followups.py FollowupItem.kind.
const KIND_LABELS: Record<FollowupKind, string> = {
  narrow: 'Narrow',
  widen: 'Widen',
  text: 'Suggestion',
};

export function SuggestedFollowupsPanel({
  followups,
  onRun,
  parentSearchSpace,
  parentStudyLoading = false,
  parentStudyError = null,
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
          {followups.map((f, i) => (
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
              {(f.kind === 'narrow' || f.kind === 'widen') && (
                <>
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
                </>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
