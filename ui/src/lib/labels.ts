// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Human-readable labels for backend wire values.
 *
 * The backend emits snake_case / lowercase enum values (`pr_merged`, `ndcg`,
 * `tpe`). Those are correct on the wire but must never reach the user verbatim.
 * This module is the single source of display labels, so the same concept reads
 * the same way everywhere (e.g. `NDCG@10`, not `ndcg` on one screen and
 * `NDCG@10` on another). Wire values still come from `@/lib/enums` — these maps
 * only decorate them for display; they never widen the type or bypass the
 * enum-source-of-truth policy.
 */

import type { JudgmentSource, ObjectiveMetric, PrunerKind, SamplerKind } from '@/lib/enums';

/** Fallback humanizer: `still_improving` → `Still improving`. */
export function humanizeWireValue(value: string): string {
  const spaced = value.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Objective-metric acronyms (uppercase; `@k` appended by formatMetricLabel). */
export const METRIC_LABELS: Record<ObjectiveMetric, string> = {
  ndcg: 'NDCG',
  map: 'MAP',
  precision: 'Precision',
  recall: 'Recall',
  mrr: 'MRR',
};

/**
 * Canonical rendering of a metric with its cutoff, used everywhere a metric is
 * shown. MRR ignores `k` (evaluates the full ranked list), so `@k` is omitted
 * when `k` is null.
 */
export function formatMetricLabel(metric: string, k: number | null): string {
  const base = METRIC_LABELS[metric as ObjectiveMetric] ?? metric.toUpperCase();
  return k != null ? `${base}@${k}` : base;
}

export const SAMPLER_LABELS: Record<SamplerKind, string> = {
  tpe: 'TPE (learns from prior trials)',
  random: 'Random',
};

export const PRUNER_LABELS: Record<PrunerKind, string> = {
  median: 'Median (early-stop weak trials)',
  none: 'None',
};

export const JUDGMENT_SOURCE_LABELS: Record<JudgmentSource, string> = {
  llm: 'LLM-as-judge',
  human: 'Human',
  click: 'Click (UBI)',
};
