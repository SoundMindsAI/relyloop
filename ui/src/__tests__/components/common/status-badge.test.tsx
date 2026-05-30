// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { StatusBadge, type StatusBadgeKind } from '@/components/common/status-badge';

interface BadgeCase {
  kind: StatusBadgeKind;
  value: string;
  expectedVariantSubstring: string;
}

const CASES: BadgeCase[] = [
  { kind: 'study', value: 'queued', expectedVariantSubstring: 'bg-gray-100' },
  { kind: 'study', value: 'running', expectedVariantSubstring: 'bg-blue-100' },
  { kind: 'study', value: 'completed', expectedVariantSubstring: 'bg-green-100' },
  { kind: 'study', value: 'cancelled', expectedVariantSubstring: 'border-gray-200' },
  { kind: 'study', value: 'failed', expectedVariantSubstring: 'bg-red-100' },
  { kind: 'trial', value: 'complete', expectedVariantSubstring: 'bg-green-100' },
  { kind: 'trial', value: 'pruned', expectedVariantSubstring: 'bg-gray-100' },
  { kind: 'trial', value: 'failed', expectedVariantSubstring: 'bg-red-100' },
  { kind: 'proposal', value: 'pending', expectedVariantSubstring: 'bg-gray-100' },
  { kind: 'proposal', value: 'pr_opened', expectedVariantSubstring: 'bg-blue-100' },
  { kind: 'proposal', value: 'pr_merged', expectedVariantSubstring: 'bg-green-100' },
  { kind: 'proposal', value: 'rejected', expectedVariantSubstring: 'border-gray-200' },
  { kind: 'proposal_pr', value: 'open', expectedVariantSubstring: 'bg-blue-100' },
  { kind: 'proposal_pr', value: 'closed', expectedVariantSubstring: 'border-gray-200' },
  { kind: 'proposal_pr', value: 'merged', expectedVariantSubstring: 'bg-green-100' },
  { kind: 'judgment_list', value: 'generating', expectedVariantSubstring: 'bg-blue-100' },
  { kind: 'judgment_list', value: 'complete', expectedVariantSubstring: 'bg-green-100' },
  { kind: 'judgment_list', value: 'failed', expectedVariantSubstring: 'bg-red-100' },
  { kind: 'health', value: 'green', expectedVariantSubstring: 'bg-green-100' },
  { kind: 'health', value: 'yellow', expectedVariantSubstring: 'bg-amber-100' },
  { kind: 'health', value: 'red', expectedVariantSubstring: 'bg-red-100' },
  { kind: 'health', value: 'unreachable', expectedVariantSubstring: 'bg-gray-100' },
];

describe('StatusBadge', () => {
  it.each(CASES)('renders kind=$kind value=$value with the documented variant', (c) => {
    const { container } = render(<StatusBadge kind={c.kind} value={c.value} />);
    const badge = container.querySelector('span[data-kind][data-value]');
    expect(badge).not.toBeNull();
    expect(badge!.className).toContain(c.expectedVariantSubstring);
    expect(badge!.getAttribute('data-kind')).toBe(c.kind);
    expect(badge!.getAttribute('data-value')).toBe(c.value);
  });

  it('renders the value as the visible label', () => {
    render(<StatusBadge kind="study" value="running" />);
    expect(screen.getByText('running')).toBeInTheDocument();
  });

  it('falls back to secondary variant for unknown (kind, value)', () => {
    const { container } = render(<StatusBadge kind={'study' as StatusBadgeKind} value="paused" />);
    const badge = container.querySelector('span[data-kind][data-value]');
    expect(badge!.className).toContain('bg-gray-100');
  });
});
