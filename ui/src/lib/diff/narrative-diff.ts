// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Sentence-level digest-narrative diff (feat_ubi_llm_study_comparison FR-4).
 *
 * Wraps `diffSentences` from jsdiff in a single place so the granularity can
 * be swapped (e.g. to `diffWordsWithSpace`) without touching the panel.
 * Returns the ordered segments plus per-side change counts for the summary.
 */

import { diffSentences } from 'diff';

export interface NarrativeSegment {
  value: string;
  /** Present only on the B (UBI) side. */
  added?: boolean;
  /** Present only on the A (LLM) side. */
  removed?: boolean;
}

export interface NarrativeDiff {
  segments: NarrativeSegment[];
  /** Count of segments added in B (not in A). */
  addedCount: number;
  /** Count of segments removed from A (not in B). */
  removedCount: number;
}

/**
 * Diff narrative A (LLM) against narrative B (UBI). `added` segments are new in
 * B; `removed` segments were dropped from A. Single swap point: change
 * `diffSentences` to `diffWordsWithSpace` here for finer granularity.
 */
export function diffNarratives(a: string, b: string): NarrativeDiff {
  const changes = diffSentences(a ?? '', b ?? '');
  let addedCount = 0;
  let removedCount = 0;
  const segments: NarrativeSegment[] = changes.map((c) => {
    if (c.added) addedCount += 1;
    if (c.removed) removedCount += 1;
    return {
      value: c.value,
      ...(c.added ? { added: true } : {}),
      ...(c.removed ? { removed: true } : {}),
    };
  });
  return { segments, addedCount, removedCount };
}
