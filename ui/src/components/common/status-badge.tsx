// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { Badge, type BadgeProps } from '@/components/ui/badge';
import { humanizeWireValue, JUDGMENT_SOURCE_LABELS } from '@/lib/labels';

type BadgeVariant = NonNullable<BadgeProps['variant']>;

/** Maps (kind, value) → shadcn Badge variant per Story 1.3 color table. */
const VARIANT_TABLE: Record<string, Record<string, BadgeVariant>> = {
  study: {
    queued: 'secondary',
    running: 'default',
    completed: 'success',
    cancelled: 'outline',
    failed: 'destructive',
  },
  trial: {
    complete: 'success',
    pruned: 'secondary',
    failed: 'destructive',
  },
  proposal: {
    pending: 'secondary',
    pr_opened: 'default',
    pr_merged: 'success',
    rejected: 'outline',
    // Phase 3 D-12: reuses the `outline` variant; visual distinction
    // from `rejected` comes from the badge label text + the row's
    // lower visual weight when the "Show superseded" toggle surfaces it.
    superseded: 'outline',
  },
  proposal_pr: {
    open: 'default',
    closed: 'outline',
    merged: 'success',
  },
  judgment_list: {
    generating: 'default',
    complete: 'success',
    failed: 'destructive',
  },
  // Judgment-list SOURCE (how ratings were produced), distinct from the
  // list's generation status above. Values: backend JudgmentSource.
  judgment_source: {
    llm: 'default',
    human: 'success',
    click: 'secondary',
  },
  health: {
    green: 'success',
    yellow: 'warning',
    red: 'destructive',
    unreachable: 'secondary',
  },
};

// Explicit display labels where the humanizer fallback would be wrong (acronym
// casing). Anything not listed falls back to `humanizeWireValue`. Keyed the
// same (kind, value) as VARIANT_TABLE.
const LABEL_TABLE: Record<string, Record<string, string>> = {
  proposal: {
    pr_opened: 'PR opened',
    pr_merged: 'PR merged',
  },
  proposal_pr: {
    open: 'Open',
    closed: 'Closed',
    merged: 'Merged',
  },
  judgment_source: JUDGMENT_SOURCE_LABELS,
};

export type StatusBadgeKind = keyof typeof VARIANT_TABLE;

export interface StatusBadgeProps {
  kind: StatusBadgeKind;
  value: string;
  className?: string;
}

export function StatusBadge({ kind, value, className }: StatusBadgeProps) {
  // `kind` is typed as StatusBadgeKind (typescript-enforced); `value` is a wire string
  // we explicitly chain-default on miss. The eslint security plugin can't see the
  // TypeScript type narrowing — suppress with cited safety argument.
  // eslint-disable-next-line security/detect-object-injection
  const variant = VARIANT_TABLE[kind]?.[value] ?? 'secondary';
  // Prefer an explicit display label; fall back to humanizing the wire value
  // (snake_case → Title case) so raw values like `pr_merged` / `still_improving`
  // never reach the user.
  // eslint-disable-next-line security/detect-object-injection
  const label = LABEL_TABLE[kind]?.[value] ?? humanizeWireValue(value);
  return (
    <Badge variant={variant} className={className} data-kind={kind} data-value={value}>
      {label}
    </Badge>
  );
}
