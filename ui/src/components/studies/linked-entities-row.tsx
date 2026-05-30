// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';

import { useCluster } from '@/lib/api/clusters';
import { useJudgmentList } from '@/lib/api/judgments';
import { useTemplate } from '@/lib/api/query-templates';
import { useQuerySet } from '@/lib/api/query-sets';
import type { StudyDetail } from '@/lib/api/studies';

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
    </div>
  );
}
