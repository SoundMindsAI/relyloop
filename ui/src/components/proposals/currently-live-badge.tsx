// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { InfoTooltip } from '@/components/common/info-tooltip';

interface CurrentlyLiveBadgeProps {
  // Optional because OpenAPI-generated types may emit `is_currently_live?: boolean`
  // for fields with backend defaults — accept undefined and null defensively.
  isCurrentlyLive?: boolean | null;
}

/**
 * Renders a "Currently live" pill when the given proposal is tracked as some
 * `config_repos.last_merged_proposal_id` (feat_config_repo_baseline_tracking
 * FR-7).
 *
 * Wraps the entire pill in `<InfoTooltip asChild>` so the whole badge surface
 * — not just a small icon — acts as the tooltip trigger. Hover or
 * keyboard-focus the pill → tooltip appears with the explanation from
 * glossary key `proposal.currently_live`.
 */
export function CurrentlyLiveBadge({ isCurrentlyLive }: CurrentlyLiveBadgeProps) {
  if (isCurrentlyLive !== true) return null;
  return (
    <InfoTooltip glossaryKey="proposal.currently_live" asChild>
      <span
        tabIndex={0}
        className="ml-2 inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 focus:outline-none focus:ring-2 focus:ring-green-400"
        data-testid="currently-live-badge"
        aria-label="Currently live — this proposal is the most recently merged for its config repo"
      >
        Currently live
      </span>
    </InfoTooltip>
  );
}
