// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { CursorPaginator } from '@/components/common/cursor-paginator';

describe('CursorPaginator', () => {
  it('renders Prev / Next / page size select / total count', () => {
    render(
      <CursorPaginator
        hasMore={true}
        onNext={() => {}}
        onPrev={() => {}}
        pageSize={50}
        onPageSizeChange={() => {}}
        totalCount={123}
      />,
    );
    expect(screen.getByTestId('paginator-prev')).toBeInTheDocument();
    expect(screen.getByTestId('paginator-next')).toBeInTheDocument();
    expect(screen.getByTestId('page-size-select')).toHaveValue('50');
    expect(screen.getByTestId('total-count')).toHaveTextContent('123 total');
  });

  it('disables Prev when onPrev is undefined', () => {
    render(
      <CursorPaginator
        hasMore={true}
        onNext={() => {}}
        pageSize={50}
        onPageSizeChange={() => {}}
      />,
    );
    expect(screen.getByTestId('paginator-prev')).toBeDisabled();
  });

  it('disables Next when hasMore is false', () => {
    render(
      <CursorPaginator
        hasMore={false}
        onNext={() => {}}
        onPrev={() => {}}
        pageSize={50}
        onPageSizeChange={() => {}}
      />,
    );
    expect(screen.getByTestId('paginator-next')).toBeDisabled();
  });

  it('calls onPageSizeChange with the new size', () => {
    const onPageSizeChange = vi.fn();
    render(
      <CursorPaginator
        hasMore={true}
        onNext={() => {}}
        pageSize={50}
        onPageSizeChange={onPageSizeChange}
      />,
    );
    fireEvent.change(screen.getByTestId('page-size-select'), { target: { value: '100' } });
    expect(onPageSizeChange).toHaveBeenCalledWith(100);
  });

  it('omits total count when not provided', () => {
    render(
      <CursorPaginator
        hasMore={true}
        onNext={() => {}}
        pageSize={50}
        onPageSizeChange={() => {}}
      />,
    );
    expect(screen.queryByTestId('total-count')).toBeNull();
  });
});
