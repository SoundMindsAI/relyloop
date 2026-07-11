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

  it('humanizes a single-word wire value for the visible label', () => {
    render(<StatusBadge kind="study" value="running" />);
    // Label is humanized (Title case); the raw wire value stays in data-value.
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.queryByText('running')).toBeNull();
  });

  it.each([
    { kind: 'proposal' as const, value: 'pr_opened', label: 'PR opened' },
    { kind: 'proposal' as const, value: 'pr_merged', label: 'PR merged' },
    { kind: 'proposal' as const, value: 'superseded', label: 'Superseded' },
    { kind: 'judgment_source' as const, value: 'llm', label: 'LLM-as-judge' },
    { kind: 'judgment_source' as const, value: 'human', label: 'Human' },
    { kind: 'judgment_source' as const, value: 'click', label: 'Click (UBI)' },
  ])('renders explicit display label for kind=$kind value=$value', ({ kind, value, label }) => {
    render(<StatusBadge kind={kind} value={value} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByText(value)).toBeNull();
  });

  it('judgment_source values get a real (non-secondary) variant, not the fallback', () => {
    // Regression: the source column previously used kind="judgment_list", whose
    // table has no llm/human/click keys, so every source fell through to the
    // secondary variant. judgment_source now maps them explicitly.
    const { container } = render(<StatusBadge kind="judgment_source" value="llm" />);
    const badge = container.querySelector('span[data-kind][data-value]');
    expect(badge!.className).toContain('bg-blue-100'); // 'default' variant, not secondary
  });

  it('falls back to secondary variant for unknown (kind, value)', () => {
    const { container } = render(<StatusBadge kind={'study' as StatusBadgeKind} value="paused" />);
    const badge = container.querySelector('span[data-kind][data-value]');
    expect(badge!.className).toContain('bg-gray-100');
  });
});
