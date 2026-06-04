// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Map a chain link's `selected_followup_kind` to a short token for the
 * "Explored: …" line on the Overnight result card.
 *
 * `feat_overnight_final_solution_phase2` Story 2 / FR-3. Pure data → data;
 * no React, no hooks, no I/O.
 *
 * The `TOKEN_RENDERERS: Record<SelectedFollowupKind, ...>` shape forces
 * exhaustiveness — adding a new value to `SELECTED_FOLLOWUP_KIND_VALUES`
 * (which mirrors backend/app/domain/study/auto_followup_strategy.py
 * SELECTED_FOLLOWUP_KIND_VALUES) breaks the build until the map is
 * extended. Mirrors the Phase 1 `CHAIN_STOP_REASON_PHRASE` pattern.
 *
 * Callers MUST filter null-token links BEFORE rendering child components
 * (per cycle-1 finding C1-3) — rendering null-token children would emit
 * dangling " → " separators.
 */

import { type SelectedFollowupKind } from '@/lib/enums';
import type { StudyChainResponse } from '@/lib/api/studies';

type StudyChainLink = StudyChainResponse['links'][number];

const SWAP_TEMPLATE_NAME_MAX_LEN = 24;

/**
 * Per-kind token renderer. The `Record<SelectedFollowupKind, ...>` type is
 * the exhaustiveness guard — if a new wire value lands in
 * `SELECTED_FOLLOWUP_KIND_VALUES` upstream, this map fails to compile until
 * the new key is added.
 */
const TOKEN_RENDERERS: Record<
  SelectedFollowupKind,
  (link: StudyChainLink, templateName: string | null) => string
> = {
  narrow_default: () => 'refined',
  narrow: () => 'narrow',
  widen: () => 'widen',
  swap_template: (link, templateName) => {
    if (templateName !== null) {
      const truncated =
        templateName.length > SWAP_TEMPLATE_NAME_MAX_LEN
          ? `${templateName.slice(0, SWAP_TEMPLATE_NAME_MAX_LEN)}…`
          : templateName;
      return `swap to ${truncated}`;
    }
    return `swap to ${link.template_id.slice(0, 6)}`;
  },
};

export function pathTokenForLink(link: StudyChainLink, templateName: string | null): string | null {
  const kind = link.selected_followup_kind;
  if (kind === null || kind === undefined) return null;
  return TOKEN_RENDERERS[kind](link, templateName);
}
