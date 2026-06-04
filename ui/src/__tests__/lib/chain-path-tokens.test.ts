// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { pathTokenForLink } from '@/lib/chain-path-tokens';
import type { StudyChainResponse } from '@/lib/api/studies';

type Link = StudyChainResponse['links'][number];

/**
 * Build a minimal StudyChainLink fixture with the selected_followup_kind +
 * template_id we want to test. Other fields are filled with defensible
 * defaults — they're irrelevant to pathTokenForLink's pure-data behavior.
 */
function makeLink(overrides: Partial<Link>): Link {
  return {
    id: '01910000-0000-7000-8000-000000000aaa',
    name: 'fixture link',
    status: 'completed',
    best_metric: 0.5,
    baseline_metric: 0.4,
    direction: 'maximize',
    delta_from_prev: null,
    proposal_id: null,
    auto_followup_depth_remaining: 0,
    failed_reason: null,
    created_at: '2026-06-04T00:00:00+00:00',
    completed_at: '2026-06-04T01:00:00+00:00',
    template_id: 'abc123def456789012345678901234567890',
    selected_followup_kind: null,
    ...overrides,
  };
}

describe('feat_overnight_final_solution_phase2 Story 2 / FR-3 — pathTokenForLink', () => {
  it('returns null for null selected_followup_kind (anchor or legacy narrow)', () => {
    expect(pathTokenForLink(makeLink({ selected_followup_kind: null }), null)).toBeNull();
  });

  it('returns "refined" for narrow_default kind (follow_suggestions fallback path)', () => {
    expect(pathTokenForLink(makeLink({ selected_followup_kind: 'narrow_default' }), null)).toBe(
      'refined',
    );
  });

  it('returns "narrow" for narrow kind', () => {
    expect(pathTokenForLink(makeLink({ selected_followup_kind: 'narrow' }), null)).toBe('narrow');
  });

  it('returns "widen" for widen kind', () => {
    expect(pathTokenForLink(makeLink({ selected_followup_kind: 'widen' }), null)).toBe('widen');
  });

  it('returns "swap to {name}" for swap_template kind with a short template name', () => {
    expect(
      pathTokenForLink(makeLink({ selected_followup_kind: 'swap_template' }), 'function-score-v1'),
    ).toBe('swap to function-score-v1');
  });

  it('truncates template names longer than 24 chars with an ellipsis', () => {
    const longName = 'this-is-a-very-long-template-name-exceeding-the-limit';
    const result = pathTokenForLink(
      makeLink({ selected_followup_kind: 'swap_template' }),
      longName,
    );
    expect(result).toBe('swap to this-is-a-very-long-temp…');
  });

  it('falls back to first 6 chars of template_id when templateName is null', () => {
    expect(
      pathTokenForLink(
        makeLink({
          selected_followup_kind: 'swap_template',
          template_id: 'abc123def456789012345678901234567890',
        }),
        null,
      ),
    ).toBe('swap to abc123');
  });
});
