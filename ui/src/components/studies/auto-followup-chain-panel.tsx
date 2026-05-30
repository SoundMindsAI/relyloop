// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { StudyDetail, StudySummary } from '@/lib/api/studies';

export interface AutoFollowupChainPanelProps {
  study: StudyDetail;
  /**
   * Direct children from GET /api/v1/studies/{id}/children.
   *
   * Named `chainChildren` (NOT `children`) to avoid React's
   * react/no-children-prop lint rule + the prop-name collision with
   * React's built-in `children` semantics.
   */
  chainChildren: StudySummary[];
}

/**
 * Auto-followup chain panel (feat_auto_followup_studies Story 3.1, FR-10
 * frontend).
 *
 * Renders the parent link (when this study is itself a chain child) +
 * the remaining-depth indicator + the direct-children table. Per D-13,
 * children are direct-only — operators navigate to a child's detail
 * page to see ITS children (depth ≤ 5 means at most 5 navigations).
 *
 * The panel is invisible when there's no chain context: no parent_study_id,
 * no auto_followup_depth set, and no children. This prevents noise on
 * studies that didn't opt into chaining.
 */
export function AutoFollowupChainPanel({
  study,
  chainChildren,
}: AutoFollowupChainPanelProps): React.ReactNode {
  const parentId = study.parent_study_id;
  const depth =
    typeof study.config?.auto_followup_depth === 'number' ? study.config.auto_followup_depth : null;
  const hasParent = parentId !== null && parentId !== undefined;
  const hasDepth = depth !== null && depth > 0;
  const hasChildren = chainChildren.length > 0;

  // Hide the panel when there's no chain context at all.
  if (!hasParent && !hasDepth && !hasChildren) {
    return null;
  }

  return (
    <Card data-testid="auto-followup-chain-panel">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          Auto-followup chain
          <InfoTooltip glossaryKey="auto_followup_chain" />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {hasParent && (
          <p data-testid="auto-followup-parent-link">
            Parent:{' '}
            <Link
              href={`/studies/${parentId}`}
              className="text-blue-600 underline-offset-4 hover:underline"
            >
              view parent study
            </Link>
          </p>
        )}
        {hasDepth && (
          <p data-testid="auto-followup-remaining-depth">
            Remaining auto-follow-ups: <span className="font-medium">{depth}</span>
            <span className="ml-2 inline-flex">
              <InfoTooltip glossaryKey="auto_followup_depth" />
            </span>
          </p>
        )}
        {hasChildren && (
          <div data-testid="auto-followup-children-table">
            <h3 className="mb-2 text-sm font-medium text-muted-foreground">Direct children</h3>
            <table className="w-full border-collapse text-left">
              <thead className="border-b text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="py-2 pr-4 font-medium">Name</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Best metric</th>
                </tr>
              </thead>
              <tbody>
                {chainChildren.map((child) => (
                  <tr key={child.id} className="border-b last:border-0">
                    <td className="py-2 pr-4">
                      <Link
                        href={`/studies/${child.id}`}
                        className="text-blue-600 underline-offset-4 hover:underline"
                      >
                        {child.name}
                      </Link>
                    </td>
                    <td className="py-2 pr-4">
                      <span className="capitalize">{child.status}</span>
                    </td>
                    <td className="py-2 pr-4">
                      {child.best_metric !== null && child.best_metric !== undefined
                        ? child.best_metric.toFixed(4)
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
