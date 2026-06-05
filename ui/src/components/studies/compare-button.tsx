// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { useStudyPair, type StudyDetail } from '@/lib/api/studies';

/**
 * "Compare with the {UBI|LLM} study" button (FR-8). Rendered only when this
 * study has a unique LLM↔UBI counterpart. The label names the *other* kind; the
 * link is canonical (LLM study as `a`, UBI study as `b`). Hidden entirely when
 * there is no pair — no disabled state.
 *
 * This study's kind is the OPPOSITE of the counterpart's `kind`, so no extra
 * judgment-list fetch is needed (Gemini PR #461).
 */
export function CompareButton({ study }: { study: StudyDetail }) {
  const pairQ = useStudyPair(study.id);

  const counterpartId = pairQ.data?.study_id ?? null;
  const counterpartKind = pairQ.data?.kind ?? null;
  if (counterpartId == null || counterpartKind == null) return null;

  // counterpart is UBI ⟺ this study is LLM (and vice versa).
  const llmId = counterpartKind === 'ubi' ? study.id : counterpartId;
  const ubiId = counterpartKind === 'ubi' ? counterpartId : study.id;
  const otherKindLabel = counterpartKind === 'ubi' ? 'UBI' : 'LLM';

  return (
    <Button asChild variant="outline" size="sm" data-testid="study-compare-button">
      <Link href={`/studies/compare?a=${llmId}&b=${ubiId}`}>
        Compare with the {otherKindLabel} study
      </Link>
    </Button>
  );
}
