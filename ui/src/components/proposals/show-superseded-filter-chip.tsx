// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { InfoTooltip } from '@/components/common/info-tooltip';

interface ShowSupersededFilterChipProps {
  isActive: boolean;
  onToggle: () => void;
}

/**
 * Two-state filter chip wired to the proposals-page URL state
 * (`?include_superseded=true`). Off state has no URL param — the
 * backend default (Phase 3 D-15 revised) omits superseded rows when
 * neither `?status=` nor `?include_superseded` is set.
 *
 * Mirrors the {@link import('./currently-live-filter-chip').CurrentlyLiveFilterChip}
 * shape so the two chips stack visually consistently on the proposals
 * page.
 */
export function ShowSupersededFilterChip({ isActive, onToggle }: ShowSupersededFilterChipProps) {
  return (
    <span className="inline-flex items-center gap-1">
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={isActive}
        className={
          isActive
            ? 'inline-flex items-center gap-1 rounded-full bg-amber-100 px-3 py-1 text-sm font-medium text-amber-800'
            : 'inline-flex items-center gap-1 rounded-full bg-gray-100 px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-200'
        }
        data-testid="proposals-show-superseded-filter-chip"
      >
        Show superseded
      </button>
      <InfoTooltip glossaryKey="proposal.show_superseded_filter" />
    </span>
  );
}
