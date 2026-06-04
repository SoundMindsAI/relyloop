// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';

import { InfoTooltip } from '@/components/common/info-tooltip';
import { useCluster } from '@/lib/api/clusters';
import { useJudgmentList } from '@/lib/api/judgments';
import { useTemplate } from '@/lib/api/query-templates';
import { useQuerySet } from '@/lib/api/query-sets';
import type { StudyDetail } from '@/lib/api/studies';
import { OVERNIGHT_STRATEGY_VALUES, type OvernightStrategy } from '@/lib/enums';

/**
 * Named + linked row of the four entities a study references — cluster,
 * query set, judgment list, template. The Study API response carries
 * only `*_id` UUIDs; this component fetches each entity by ID to render
 * its name + a clickable link, mirroring the pattern the proposal
 * detail page uses (`ProposalHeader`).
 *
 * Each fetch is React-Query cached, so revisits and tab-switches are
 * free. While a fetch is in flight, the slot falls back to a truncated
 * UUID prefix so the row still renders + is clickable.
 */
function Entry({
  label,
  href,
  name,
  fallback,
  testid,
}: {
  label: string;
  href: string;
  name: string | undefined;
  fallback: string;
  testid: string;
}) {
  return (
    <span data-testid={testid}>
      <span className="text-muted-foreground">{label}:</span>{' '}
      <Link href={href} className="text-blue-600 underline-offset-4 hover:underline">
        {name ?? `${fallback.slice(0, 8)}…`}
      </Link>
    </span>
  );
}

export function LinkedEntitiesRow({ study }: { study: StudyDetail }) {
  const cluster = useCluster(study.cluster_id);
  const querySet = useQuerySet(study.query_set_id);
  const judgmentList = useJudgmentList(study.judgment_list_id);
  const template = useTemplate(study.template_id);

  return (
    <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm" data-testid="study-linked-entities-row">
      <Entry
        label="Cluster"
        href={`/clusters/${study.cluster_id}`}
        name={cluster.data?.name}
        fallback={study.cluster_id}
        testid="linked-cluster"
      />
      <Entry
        label="Query set"
        href={`/query-sets/${study.query_set_id}`}
        name={querySet.data?.name}
        fallback={study.query_set_id}
        testid="linked-query-set"
      />
      <Entry
        label="Judgment list"
        href={`/judgments/${study.judgment_list_id}`}
        name={judgmentList.data?.name}
        fallback={study.judgment_list_id}
        testid="linked-judgment-list"
      />
      <Entry
        label="Template"
        href={`/templates/${study.template_id}`}
        name={template.data?.name}
        fallback={study.template_id}
        testid="linked-template"
      />
      <Entry
        label="Index"
        href={`/clusters/${encodeURIComponent(study.cluster_id)}/indices/${encodeURIComponent(study.target)}`}
        name={study.target}
        fallback={study.target}
        testid="linked-index"
      />
      <StrategyLine study={study} />
    </div>
  );
}

// Source-of-truth: ui/src/lib/enums.ts OVERNIGHT_STRATEGY_VALUES
// (mirrors backend/app/api/v1/schemas.py AUTO_FOLLOWUP_STRATEGY_VALUES).
// Per CLAUDE.md "Enumerated Value Contract Discipline" — the display
// mapping is keyed by the typed OvernightStrategy literal so a new wire
// value lands a build break until the mapping is extended.
const STRATEGY_DISPLAY: Record<OvernightStrategy, string> = {
  narrow: 'Refine same knobs',
  follow_suggestions: 'Try suggested follow-ups',
};

/**
 * feat_overnight_final_solution_phase2 Story 5 / FR-2 — read-only line
 * surfacing this study's overnight-followup strategy. Renders ONLY when
 * `study.config.auto_followup_strategy` is one of the values in
 * OVERNIGHT_STRATEGY_VALUES. Hidden for null / missing / unknown values
 * (defensive — Phase 1 D-13 makes the backend field `str | None`, so a
 * malformed JSONB value could in principle reach the frontend).
 */
function StrategyLine({ study }: { study: StudyDetail }) {
  const raw = (study.config as { auto_followup_strategy?: unknown } | null | undefined)
    ?.auto_followup_strategy;
  if (typeof raw !== 'string') return null;
  if (!(OVERNIGHT_STRATEGY_VALUES as readonly string[]).includes(raw)) return null;
  const strategy = raw as OvernightStrategy;
  return (
    // Per Gemini cycle-1 review on PR #442: use inline-flex + gap-1 for
    // tighter vertical alignment of label + value + tooltip icon, mirroring
    // the spacing rhythm used by InfoTooltip inline icons elsewhere in the
    // study detail page.
    <span data-testid="study-strategy-line" className="inline-flex items-center gap-1">
      <span className="text-muted-foreground">Strategy:</span>
      <span>{STRATEGY_DISPLAY[strategy]}</span>
      <InfoTooltip glossaryKey="auto_followup_strategy_line" />
    </span>
  );
}
