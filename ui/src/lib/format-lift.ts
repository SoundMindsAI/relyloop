// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Format a signed lift/delta value with a leading `+`/`-` and 4 decimals.
 *
 * Returns '—' for null/undefined (matches the chain panel's empty-cell
 * convention). Extracted by `feat_overnight_final_solution_phase2` Story 1
 * / FR-8 / D-12 so both `<AutoFollowupChainPanel>` and the new
 * `<OvernightResultCard>` consume identical formatting — the same lift
 * number must never appear in two different formats on the same page.
 */
export function formatSignedLift(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(4)}`;
}
