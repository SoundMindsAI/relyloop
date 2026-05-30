// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Cardinality counters (Story 2.3, FR-6 + FR-7).
 *
 * `<RowCardinality>` renders a single param's contribution
 * (`estimateParamCardinality`). `<HeaderCardinality>` renders the
 * product total + cap-warning + max-contributor hint when > 10^6.
 *
 * FR-7 invariant: cardinality is **warning-only** — does NOT block
 * Next. The server-side `_check_cardinality` at
 * `backend/app/domain/study/search_space.py:111-118` remains the
 * authoritative gate.
 */

import * as React from 'react';

import {
  estimateCardinality,
  estimateParamCardinality,
  type ParamSpec,
  type SearchSpaceJson,
} from '@/lib/search-space-defaults';

const CARDINALITY_CAP = 1_000_000;

function formatCount(n: number): string {
  // Use exponential notation for large numbers, plain for small.
  if (n >= 100_000) return `~${n.toExponential(2)}`;
  return n.toLocaleString();
}

export interface RowCardinalityProps {
  paramName: string;
  spec: ParamSpec;
}

export function RowCardinality({ paramName, spec }: RowCardinalityProps): React.ReactElement {
  const n = estimateParamCardinality(spec);
  const detail =
    spec.type === 'float'
      ? `≈ ${n} states (log float)`
      : spec.type === 'int'
        ? `${n} states (${spec.high} − ${spec.low} + 1)`
        : `${n} states`;
  return (
    <span data-testid={`cs-row-${paramName}-cardinality`} className="text-xs text-muted-foreground">
      {detail}
    </span>
  );
}

export interface HeaderCardinalityProps {
  space: SearchSpaceJson;
}

export function HeaderCardinality({ space }: HeaderCardinalityProps): React.ReactElement {
  const total = estimateCardinality(space);
  const overCap = total > CARDINALITY_CAP;

  const maxContributor: { name: string; contribution: number } | null = overCap
    ? Object.entries(space.params).reduce<{ name: string; contribution: number } | null>(
        (acc, [name, spec]) => {
          const contribution = estimateParamCardinality(spec);
          if (acc === null || contribution > acc.contribution) {
            return { name, contribution };
          }
          return acc;
        },
        null,
      )
    : null;

  return (
    <div className="space-y-1" data-testid="cs-builder-header-cardinality-block">
      <p
        data-testid="cs-builder-header-cardinality"
        aria-invalid={overCap ? true : undefined}
        className={
          overCap ? 'text-sm text-destructive font-medium' : 'text-sm text-muted-foreground'
        }
      >
        Search space: {formatCount(total)} combinations (cap: 1,000,000)
      </p>
      {overCap && maxContributor !== null && (
        <p data-testid="cs-builder-cap-hint" className="text-sm text-destructive">
          Try narrowing <code className="font-mono">{maxContributor.name}</code> — currently{' '}
          {maxContributor.contribution.toLocaleString()} of {formatCount(total)}
        </p>
      )}
    </div>
  );
}
