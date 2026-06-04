// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Shared mapping from `StudyChainResponse.stop_reason` to a friendly phrase.
 *
 * Extracted by `feat_overnight_final_solution_phase2` Story 1 / FR-8 from the
 * inline declaration that previously lived in
 * `ui/src/components/studies/auto-followup-chain-panel.tsx`. Both the chain
 * panel and the new Overnight result card consume this map; centralising it
 * eliminates the drift risk of two copies of the same constant rendering the
 * same lift number on the same page in different ways.
 *
 * Source-of-truth: backend/app/domain/study/chain_summary.py CHAIN_STOP_REASONS
 */

import type { StudyChainResponse } from '@/lib/api/studies';

type ChainStopReason = NonNullable<StudyChainResponse['stop_reason']>;

export const CHAIN_STOP_REASON_PHRASE: Record<ChainStopReason, string> = {
  depth_exhausted: 'depth budget exhausted',
  no_lift: 'no further improvement',
  budget: 'daily LLM budget reached',
  parent_failed: 'parent study failed or was cancelled',
  cancelled: 'operator cancelled the chain',
  in_flight: 'chain still running',
};
