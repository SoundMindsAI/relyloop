// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const pairMock = vi.fn();

vi.mock('@/lib/api/studies', () => ({ useStudyPair: () => pairMock() }));

import { CompareButton } from '@/components/studies/compare-button';

const STUDY = { id: 'llm-1', judgment_list_id: 'jl-1' } as never;

afterEach(() => vi.clearAllMocks());

describe('CompareButton (FR-8)', () => {
  it('hidden when there is no counterpart', () => {
    pairMock.mockReturnValue({ data: { study_id: null, kind: null } });
    render(<CompareButton study={STUDY} />);
    expect(screen.queryByTestId('study-compare-button')).toBeNull();
  });

  it('UBI counterpart → labels UBI, this study is LLM=a', () => {
    pairMock.mockReturnValue({ data: { study_id: 'ubi-9', kind: 'ubi' } });
    render(<CompareButton study={STUDY} />);
    const btn = screen.getByTestId('study-compare-button');
    expect(btn).toHaveTextContent('Compare with the UBI study');
    expect(btn).toHaveAttribute('href', '/studies/compare?a=llm-1&b=ubi-9');
  });

  it('LLM counterpart → labels LLM, keeps the LLM study as a', () => {
    pairMock.mockReturnValue({ data: { study_id: 'llm-7', kind: 'llm' } });
    render(<CompareButton study={STUDY} />);
    const btn = screen.getByTestId('study-compare-button');
    expect(btn).toHaveTextContent('Compare with the LLM study');
    // this study (llm-1) is UBI here → b; counterpart llm-7 → a.
    expect(btn).toHaveAttribute('href', '/studies/compare?a=llm-7&b=llm-1');
  });
});
