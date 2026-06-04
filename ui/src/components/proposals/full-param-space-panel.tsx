// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { renderValue } from '@/lib/config-diff';
import {
  partitionTemplateParams,
  type DeclaredRow,
  type ParamSpaceGroup,
  type TunedChangedRow,
} from '@/lib/proposal-param-space';

// feat_proposal_full_param_space_view Story 1.3 — render every parameter the
// proposal's template declares, partitioned into three visually distinct
// groups (tuned-changed / tuned-unchanged / not-in-search-space) so operators
// can see what the optimizer left on the table. Consumes the pure
// partitionTemplateParams helper (Story 1.2) + the shared renderValue (Story
// 1.1). The component is a thin renderer over a tested contract.

export interface FullParamSpacePanelProps {
  configDiff: Record<string, unknown>;
  declaredParams: Record<string, string>;
  // `null` is reachable from JSONB `search_space.params` (see PartitionInput).
  searchSpaceParams?: Record<string, unknown> | null | undefined;
}

// Human-facing group headers, keyed by the internal ParamSpaceGroup discriminant.
// D-12: the group identity lives on the containing array, NOT on individual rows.
const GROUP_LABELS: Record<ParamSpaceGroup, string> = {
  tuned_changed: 'Tuned (changed by this proposal)',
  tuned_unchanged: 'Tuned (unchanged)',
  untuned: 'Not in search space',
};

function GroupHeader({ group, count }: { group: ParamSpaceGroup; count: number }) {
  return (
    <h3
      className="mt-3 text-sm font-semibold text-gray-900 first:mt-0"
      data-testid={`param-space-group-${group}`}
    >
      {GROUP_LABELS[group]} — {count} {count === 1 ? 'parameter' : 'parameters'}
    </h3>
  );
}

function TunedChangedRows({ rows }: { rows: TunedChangedRow[] }) {
  // Grid (not flex) so name / type / from / → / to align vertically across
  // rows of varying name lengths — matches <ConfigDiffPanel>'s table columns
  // (Gemini G2).
  return (
    <ul className="mt-1 space-y-0.5">
      {rows.map((row) => (
        <li
          key={row.name}
          data-testid={`param-space-row-tuned_changed-${row.name}`}
          className="grid grid-cols-[1.5fr_1fr_1fr_auto_1fr] items-center gap-x-3 font-mono text-xs text-gray-700"
        >
          <code>{row.name}</code>
          <span className="text-muted-foreground">{row.type}</span>
          <span className="justify-self-end">{renderValue(row.from)}</span>
          <span aria-hidden="true" className="text-center text-muted-foreground">
            →
          </span>
          <span>{renderValue(row.to)}</span>
        </li>
      ))}
    </ul>
  );
}

function DeclaredRows({
  group,
  rows,
}: {
  group: 'tuned_unchanged' | 'untuned';
  rows: DeclaredRow[];
}) {
  const italic = group === 'untuned' ? 'italic' : '';
  return (
    <ul className="mt-1 space-y-0.5">
      {rows.map((row) => (
        <li
          key={row.name}
          data-testid={`param-space-row-${group}-${row.name}`}
          className={`text-xs text-gray-700 ${italic}`.trim()}
        >
          <code className="text-xs">{row.name}</code>: {row.type}
          {group === 'tuned_unchanged' && (
            <span className="ml-2 text-xs text-muted-foreground">(no change)</span>
          )}
        </li>
      ))}
    </ul>
  );
}

export function FullParamSpacePanel({
  configDiff,
  declaredParams,
  searchSpaceParams,
}: FullParamSpacePanelProps) {
  const partition = partitionTemplateParams({ configDiff, declaredParams, searchSpaceParams });
  // Full-partition-universe empty: both declared params AND config_diff empty
  // (the AC-6 drift path takes precedence when config_diff has keys).
  const isEmpty = Object.keys(declaredParams).length === 0 && Object.keys(configDiff).length === 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1 text-base">
          Full parameter space
          <InfoTooltip glossaryKey="proposal.full_param_space" />
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isEmpty ? (
          <p
            className="py-6 text-center text-sm text-muted-foreground"
            data-testid="param-space-empty"
          >
            Template declares no parameters.
          </p>
        ) : (
          <div className="space-y-1">
            {partition.tunedChanged.length > 0 && (
              <div>
                <GroupHeader group="tuned_changed" count={partition.tunedChanged.length} />
                <TunedChangedRows rows={partition.tunedChanged} />
              </div>
            )}
            {partition.tunedUnchanged.length > 0 && (
              <div>
                <GroupHeader group="tuned_unchanged" count={partition.tunedUnchanged.length} />
                <DeclaredRows group="tuned_unchanged" rows={partition.tunedUnchanged} />
              </div>
            )}
            {partition.untuned.length > 0 && (
              <div>
                <GroupHeader group="untuned" count={partition.untuned.length} />
                <DeclaredRows group="untuned" rows={partition.untuned} />
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
