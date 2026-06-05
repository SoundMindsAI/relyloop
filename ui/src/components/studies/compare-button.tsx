// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { useJudgmentList } from '@/lib/api/judgments';
import { useStudyPair, type StudyDetail } from '@/lib/api/studies';

/**
 * "Compare with the {UBI|LLM} study" button (FR-8). Rendered only when this
 * study has a unique LLM↔UBI counterpart. The label names the *other* kind; the
 * link is canonical (LLM study as `a`, UBI study as `b`). Hidden entirely when
 * there is no pair — no disabled state.
 */
export function CompareButton({ study }: { study: StudyDetail }) {
  const pairQ = useStudyPair(study.id);
  const jlQ = useJudgmentList(study.judgment_list_id);

  const counterpartId = pairQ.data?.study_id ?? null;
  if (counterpartId == null) return null;

  const thisIsUbi =
    (jlQ.data?.generation_params as Record<string, unknown> | null | undefined)?.[
      'generation_kind'
    ] === 'ubi';
  const llmId = thisIsUbi ? counterpartId : study.id;
  const ubiId = thisIsUbi ? study.id : counterpartId;
  // The button labels the OTHER study's kind (== pairQ.data.kind).
  const otherKindLabel = pairQ.data?.kind === 'ubi' ? 'UBI' : 'LLM';

  return (
    <Button asChild variant="outline" size="sm" data-testid="study-compare-button">
      <Link href={`/studies/compare?a=${llmId}&b=${ubiId}`}>
        Compare with the {otherKindLabel} study
      </Link>
    </Button>
  );
}
