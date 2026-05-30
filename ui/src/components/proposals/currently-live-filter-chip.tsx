// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { InfoTooltip } from '@/components/common/info-tooltip';

interface CurrentlyLiveFilterChipProps {
  isActive: boolean;
  onToggle: () => void;
}

/**
 * Two-state filter chip wired to the proposals-page URL state
 * (`?is_last_merged=true`). Off state has no URL param (the API's
 * `?is_last_merged=false` complement is intentionally NOT exposed in
 * the chip — it stays API-only per spec §19 decision-log).
 *
 * Chip and `<InfoTooltip>` are rendered as siblings inside a wrapper
 * `<span>` so the chip's `onClick` handles toggle and the info trigger
 * handles its own keyboard / tooltip semantics — no nested buttons.
 */
export function CurrentlyLiveFilterChip({ isActive, onToggle }: CurrentlyLiveFilterChipProps) {
  return (
    <span className="inline-flex items-center gap-1">
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={isActive}
        className={
          isActive
            ? 'inline-flex items-center gap-1 rounded-full bg-green-100 px-3 py-1 text-sm font-medium text-green-800'
            : 'inline-flex items-center gap-1 rounded-full bg-gray-100 px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-200'
        }
        data-testid="proposals-currently-live-filter-chip"
      >
        Currently live only
      </button>
      <InfoTooltip glossaryKey="proposal.currently_live_filter" />
    </span>
  );
}
