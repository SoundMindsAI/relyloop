// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import * as React from 'react';

import { HelpPopover } from '@/components/common/help-popover';
import type { UbiReadinessRung } from '@/lib/enums';

const RUNG_LABELS: Record<UbiReadinessRung, string> = {
  rung_0: 'UBI not enabled',
  rung_1: 'UBI sparse',
  rung_2: 'UBI dense head',
  rung_3: 'UBI full coverage',
};

interface UbiRungBadgeProps {
  rung: UbiReadinessRung;
}

/**
 * `<UbiRungBadge>` — text-only badge for the UBI readiness rung
 * (feat_ubi_judgments Story 4.1 / FR-7 + FR-8).
 *
 * Single variant (no "snapshot" mode — cycle-3 plan-review fix
 * `readiness-snapshot-badge-contract-drift`). Spec FR-7 requires
 * `?query_set_id` and `?target` query params to call the readiness
 * endpoint; cluster-list / cluster-detail pages don't have those in
 * context, so this badge is consumed ONLY inside the generate-
 * judgments dialog (Story 4.2) where the parent component has all
 * three values to call `useUbiReadiness(...)`.
 *
 * The tooltip is keyed off the `cluster.ubi_readiness` glossary
 * entry (long-form description of all four rungs).
 */
export function UbiRungBadge({ rung }: UbiRungBadgeProps): React.ReactElement {
  const label = RUNG_LABELS[rung];
  return (
    <span
      data-testid="ubi-rung-badge"
      data-rung={rung}
      className="inline-flex items-center gap-1 rounded-sm bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
    >
      <span>{label}</span>
      <HelpPopover glossaryKey="cluster.ubi_readiness" />
    </span>
  );
}
