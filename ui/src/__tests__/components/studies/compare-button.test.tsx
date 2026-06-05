// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const pairMock = vi.fn();
const jlMock = vi.fn();

vi.mock('@/lib/api/studies', () => ({ useStudyPair: () => pairMock() }));
vi.mock('@/lib/api/judgments', () => ({ useJudgmentList: () => jlMock() }));

import { CompareButton } from '@/components/studies/compare-button';

const STUDY = { id: 'llm-1', judgment_list_id: 'jl-1' } as never;

afterEach(() => vi.clearAllMocks());

describe('CompareButton (FR-8)', () => {
  it('hidden when there is no counterpart', () => {
    pairMock.mockReturnValue({ data: { study_id: null, kind: null } });
    jlMock.mockReturnValue({ data: { generation_params: null } });
    render(<CompareButton study={STUDY} />);
    expect(screen.queryByTestId('study-compare-button')).toBeNull();
  });

  it('on an LLM study, labels the UBI counterpart + builds the canonical href', () => {
    pairMock.mockReturnValue({ data: { study_id: 'ubi-9', kind: 'ubi' } });
    jlMock.mockReturnValue({ data: { generation_params: null } }); // this study is LLM
    render(<CompareButton study={STUDY} />);
    const btn = screen.getByTestId('study-compare-button');
    expect(btn).toHaveTextContent('Compare with the UBI study');
    // canonical: a = LLM study, b = UBI study
    expect(btn).toHaveAttribute('href', '/studies/compare?a=llm-1&b=ubi-9');
  });

  it('on a UBI study, labels the LLM counterpart + keeps LLM as `a`', () => {
    pairMock.mockReturnValue({ data: { study_id: 'llm-7', kind: 'llm' } });
    jlMock.mockReturnValue({ data: { generation_params: { generation_kind: 'ubi' } } });
    render(<CompareButton study={STUDY} />);
    const btn = screen.getByTestId('study-compare-button');
    expect(btn).toHaveTextContent('Compare with the LLM study');
    expect(btn).toHaveAttribute('href', '/studies/compare?a=llm-7&b=llm-1');
  });
});
